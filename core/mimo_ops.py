"""

El receptor MIMO trabaja por subportadora OFDM. En cada subportadora se resuelve:

    r[k] = H_eff[k] s[k] + n[k]

`r[k]` es el vector recibido en las antenas RX, `s[k]` son las capas espaciales
y `H_eff[k]` es la matriz de canal efectiva. 

Las columnas de `H_eff[k]` son las contribuciones espaciales de cada capa:

    r = h1*s1 + h2*s2 + ... + n
"""

import numpy as np

from .utils import quantize_symbols_to_constellation


def mimo_precoder_matrix(n_tx, n_layers=None, precoder="identity"):
    """Devuelve W, la matriz que mapea capas espaciales a antenas TX fisicas."""
    n_tx = int(n_tx)
    n_layers = n_tx if n_layers is None else int(n_layers)
    if n_tx <= 0 or n_layers <= 0:
        raise ValueError("n_tx y n_layers deben ser positivos")
    if n_layers > n_tx:
        raise ValueError("No puede haber mas capas que antenas TX")

    if isinstance(precoder, np.ndarray):
        matrix = np.asarray(precoder, dtype=np.complex128)
    else:
        mode = "identity" if precoder is None else str(precoder).lower()
        if mode == "identity":
            if n_tx != n_layers:
                raise ValueError("El precoder identidad requiere n_tx == n_layers")
            matrix = np.eye(n_tx, dtype=np.complex128)
        elif mode in ("tx_repeat", "repeat"):
            if n_tx % n_layers != 0:
                raise ValueError("tx_repeat requiere que n_tx sea multiplo de n_layers")
            repeats = n_tx // n_layers
            matrix = np.zeros((n_tx, n_layers), dtype=np.complex128)
            for tx_idx in range(n_tx):
                matrix[tx_idx, tx_idx % n_layers] = 1 / np.sqrt(repeats)
        else:
            raise ValueError("Precoder MIMO no soportado")

    if matrix.shape != (n_tx, n_layers):
        raise ValueError("La matriz de precoding debe tener forma n_tx x n_layers")
    gram = matrix.conj().T @ matrix
    if not np.allclose(gram, np.eye(n_layers), atol=1e-10):
        raise ValueError("La matriz de precoding debe tener columnas ortonormales")
    return matrix


def effective_mimo_channel(h_physical, precoder_matrix, channel_scale=1.0):
    """Calcula H_eff[k] = H_phys[k] W para cada subportadora activa.

    Formas esperadas:

    - `h_physical`: `(num_subportadoras, n_rx, n_tx)`.
    - `precoder_matrix`: `(n_tx, n_layers)`.
    - retorno: `(num_subportadoras, n_rx, n_layers)`.
    """
    h_physical = np.asarray(h_physical, dtype=np.complex128)
    precoder_matrix = np.asarray(precoder_matrix, dtype=np.complex128)
    if h_physical.ndim != 3:
        raise ValueError("H fisico debe tener forma subportadoras x n_rx x n_tx")
    if precoder_matrix.ndim != 2:
        raise ValueError("W debe ser una matriz n_tx x n_layers")
    if h_physical.shape[2] != precoder_matrix.shape[0]:
        raise ValueError("H fisico y W no tienen dimensiones compatibles")
    return np.einsum("krt,tl->krl", h_physical, precoder_matrix) * complex(channel_scale)


def solve_mimo_zf(received_vectors, effective_channel, threshold=1e-10):
    """Resuelve s_hat = pinv(H_eff) r por subportadora."""
    weights = np.linalg.pinv(effective_channel, rcond=threshold)
    return np.einsum("bij,bj->bi", weights, received_vectors)


def solve_mimo_mmse(received_vectors, effective_channel, noise_to_signal=0.0, threshold=1e-10):
    """Resuelve el detector MMSE lineal.

    Ecuacion teorica por subportadora:

        s_hat = (H^H H + sigma2 I)^-1 H^H r

    El codigo usa `np.linalg.solve` para resolver el sistema lineal sin formar
    explicitamente la inversa.
    """
    h_herm = np.swapaxes(effective_channel.conj(), -1, -2)
    gram = h_herm @ effective_channel
    n_layers = effective_channel.shape[2]
    sigma2 = max(0.0, float(noise_to_signal))
    gram = gram + sigma2 * np.eye(n_layers, dtype=np.complex128)[None, :, :]
    rhs = h_herm @ received_vectors[:, :, None]

    try:
        return np.linalg.solve(gram, rhs)[:, :, 0]
    except np.linalg.LinAlgError:
        return (np.linalg.pinv(gram, rcond=threshold) @ rhs)[:, :, 0]


def layer_order_by_channel_power(effective_channel):
    """Ordena capas de mayor a menor potencia de canal.

    Para r = h1*s1 + h2*s2 + n, compara:

        ||h1||^2 = |h11|^2 + |h21|^2 + ...
        ||h2||^2 = |h12|^2 + |h22|^2 + ...

    Es el criterio didactico usado por SIC para decidir que capa cancelar
    primero.
    """
    layer_power = np.sum(np.abs(effective_channel) ** 2, axis=1)
    return np.argsort(-layer_power, axis=1)


def cancel_detected_layer(residual, effective_channel, chosen_layers, decided_symbols):
    """Resta del residual la contribucion de una capa ya decidida.

    Si se decide la capa i:

        residual <- residual - h_i * s_i_decidido
    """
    batch_indices = np.arange(residual.shape[0])
    layer_channels = effective_channel[batch_indices, :, chosen_layers]
    return residual - layer_channels * decided_symbols[:, None]


def solve_mimo_mmse_sic(
    received_vectors,
    effective_channel,
    mod_type,
    noise_to_signal=0.0,
    threshold=1e-10,
):
    """Detecta capas con MMSE-SIC.

    Flujo por subportadora:

    1. residual = r.
    2. Escoger la capa con mayor ||h_i||^2.
    3. Estimar capas activas con MMSE.
    4. Decidir el simbolo QAM mas cercano de la capa escogida.
    5. Restar h_i*s_i_decidido del residual.
    6. Repetir hasta detectar todas las capas.
    """
    if mod_type is None:
        raise ValueError("MMSE-SIC requiere el tipo de modulacion")

    batch_size, _ = received_vectors.shape
    n_layers = effective_channel.shape[2]
    residual = received_vectors.copy()
    active_layers = np.ones((batch_size, n_layers), dtype=bool)
    detected = np.zeros((batch_size, n_layers), dtype=np.complex128)

    detection_order = layer_order_by_channel_power(effective_channel)
    batch_indices = np.arange(batch_size)

    for step_idx in range(n_layers):
        active_channel = effective_channel * active_layers[:, None, :]
        layer_estimates = solve_mimo_mmse(
            residual,
            active_channel,
            noise_to_signal=max(float(noise_to_signal), threshold),
            threshold=threshold,
        )

        chosen_layers = detection_order[:, step_idx]
        decided_symbols = quantize_symbols_to_constellation(
            layer_estimates[batch_indices, chosen_layers],
            mod_type,
        )

        detected[batch_indices, chosen_layers] = decided_symbols
        residual = cancel_detected_layer(
            residual,
            effective_channel,
            chosen_layers,
            decided_symbols,
        )
        active_layers[batch_indices, chosen_layers] = False

    return detected


def detect_mimo_symbols(
    received_vectors,
    effective_channel,
    detector="MMSE",
    noise_to_signal=0.0,
    threshold=1e-10,
    mod_type=None,
):
    """Detecta s en r = H_eff s + n usando ZF, MMSE o MMSE-SIC.

    `received_vectors` puede ser un solo vector `(n_rx,)` o un lote
    `(batch, n_rx)`. En OFDM, el lote normalmente son las subportadoras activas
    de un bloque.
    """
    received_vectors = np.asarray(received_vectors, dtype=np.complex128)
    effective_channel = np.asarray(effective_channel, dtype=np.complex128)
    detector = str(detector).upper()

    squeeze = received_vectors.ndim == 1
    if squeeze:
        received_vectors = received_vectors[None, :]
        effective_channel = effective_channel[None, :, :]

    if effective_channel.ndim != 3 or received_vectors.ndim != 2:
        raise ValueError("Las dimensiones de entrada MIMO no son validas")
    if (
        effective_channel.shape[0] != received_vectors.shape[0]
        or effective_channel.shape[1] != received_vectors.shape[1]
    ):
        raise ValueError("La matriz de canal y la senal recibida no coinciden")

    if detector == "ZF":
        detected = solve_mimo_zf(received_vectors, effective_channel, threshold)
    elif detector == "MMSE":
        detected = solve_mimo_mmse(
            received_vectors,
            effective_channel,
            noise_to_signal=noise_to_signal,
            threshold=threshold,
        )
    elif detector in ("MMSE-SIC", "SIC"):
        detected = solve_mimo_mmse_sic(
            received_vectors,
            effective_channel,
            mod_type=mod_type,
            noise_to_signal=noise_to_signal,
            threshold=threshold,
        )
    else:
        raise ValueError("Detector MIMO no soportado")

    return detected[0] if squeeze else detected
