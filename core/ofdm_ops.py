import numpy as np

from .mimo_ops import (
    detect_mimo_symbols,
    effective_mimo_channel,
    mimo_precoder_matrix,
)


def active_subcarrier_indices(n_fft, nc):
    """
    Indices FFT de subportadoras activas alrededor de DC.

    El orden devuelto va de frecuencias negativas a positivas y deja el bin DC
    en cero, como en la generacion OFDM baseband de LTE.
    """
    if nc % 2:
        raise ValueError("El numero de subportadoras activas debe ser par")
    if nc >= n_fft:
        raise ValueError("Las subportadoras activas deben caber dentro de la FFT")

    half = nc // 2
    negative = np.arange(n_fft - half, n_fft)
    positive = np.arange(1, half + 1)
    return np.concatenate((negative, positive))


def channel_frequency_response(h, n_fft, nc):
    """Calcula H[k] en las subportadoras activas desde la respuesta impulsiva."""
    h = np.asarray(h, dtype=np.complex128)
    active_indices = active_subcarrier_indices(n_fft, nc)
    if h.ndim == 1:
        return np.fft.fft(h, n=n_fft)[active_indices]
    if h.ndim == 3:
        h_freq = np.fft.fft(h, n=n_fft, axis=-1)
        return np.moveaxis(h_freq[:, :, active_indices], -1, 0)
    raise ValueError("La respuesta de canal debe ser SISO 1D o MIMO 3D")


def _map_active_grid_to_time(active_grid, n_fft, nc):
    freq_grid = np.zeros((active_grid.shape[0], n_fft), dtype=np.complex128)
    freq_grid[:, active_subcarrier_indices(n_fft, nc)] = active_grid
    return np.fft.ifft(freq_grid, axis=1) * np.sqrt(n_fft)


def _time_to_active_grid(rx_time_signal, n_fft, nc):
    rx_time_signal = np.asarray(rx_time_signal, dtype=np.complex128)
    num_blocks = len(rx_time_signal) // n_fft
    if num_blocks == 0:
        return np.empty((0, nc), dtype=np.complex128)

    blocks = rx_time_signal[:num_blocks * n_fft].reshape(num_blocks, n_fft)
    fft_out = np.fft.fft(blocks, axis=1) / np.sqrt(n_fft)
    return fft_out[:, active_subcarrier_indices(n_fft, nc)]


def _time_to_active_grid_multi(rx_time_signals, n_fft, nc):
    rx_time_signals = np.asarray(rx_time_signals, dtype=np.complex128)
    if rx_time_signals.ndim == 1:
        rx_time_signals = rx_time_signals[None, :]
    if rx_time_signals.ndim != 2:
        raise ValueError("La senal MIMO recibida debe ser 1D o 2D")

    grids = [
        _time_to_active_grid(rx_time_signals[rx_idx], n_fft, nc)
        for rx_idx in range(rx_time_signals.shape[0])
    ]
    if not grids:
        return np.empty((0, 0, nc), dtype=np.complex128)
    return np.stack(grids, axis=0)


def _cp_lengths_for_blocks(cp_config, num_blocks, n_fft):
    if np.isscalar(cp_config):
        cp_len = int(n_fft * cp_config) if isinstance(cp_config, float) else int(cp_config)
        return np.full(num_blocks, cp_len, dtype=int)

    cp_pattern = np.asarray(cp_config, dtype=int)
    if cp_pattern.ndim != 1 or len(cp_pattern) == 0:
        raise ValueError("El patron de CP no es valido")

    repeats = int(np.ceil(num_blocks / len(cp_pattern)))
    return np.tile(cp_pattern, repeats)[:num_blocks]


def modulate_ofdm(symbols, n_fft, nc):
    """Mapea todos los simbolos QAM a subportadoras activas y aplica IFFT."""
    symbols = np.asarray(symbols, dtype=np.complex128)
    num_symbols = len(symbols)
    num_blocks = int(np.ceil(num_symbols / nc)) if num_symbols else 0
    if num_blocks == 0:
        return np.array([], dtype=np.complex128), 0

    padded = np.zeros(num_blocks * nc, dtype=np.complex128)
    padded[:num_symbols] = symbols
    active_grid = padded.reshape(num_blocks, nc)
    time_grid = _map_active_grid_to_time(active_grid, n_fft, nc)
    return time_grid.reshape(-1), num_blocks


def _split_symbols_into_layers(symbols, n_layers, num_blocks, data_per_layer):
    layer_capacity = num_blocks * data_per_layer
    layer_grid = np.zeros((n_layers, layer_capacity), dtype=np.complex128)
    for layer_idx in range(n_layers):
        layer_symbols = symbols[layer_idx::n_layers]
        layer_grid[layer_idx, : len(layer_symbols)] = layer_symbols
    return layer_grid.reshape(n_layers, num_blocks, data_per_layer)


def _interleave_layer_symbols(layer_symbols):
    layer_symbols = np.asarray(layer_symbols, dtype=np.complex128)
    if layer_symbols.ndim != 2:
        raise ValueError("Los simbolos por capa deben ser una matriz 2D")

    n_layers, layer_len = layer_symbols.shape
    interleaved = np.zeros(n_layers * layer_len, dtype=np.complex128)
    for layer_idx in range(n_layers):
        interleaved[layer_idx::n_layers] = layer_symbols[layer_idx]
    return interleaved


def modulate_mimo_ofdm(
    symbols,
    n_fft,
    nc,
    n_tx=2,
    n_layers=None,
    precoder="identity",
):
    """Genera senales OFDM por antena TX usando todas las subportadoras activas."""
    symbols = np.asarray(symbols, dtype=np.complex128)
    n_tx = int(n_tx)
    n_layers = n_tx if n_layers is None else int(n_layers)
    precoder_matrix = mimo_precoder_matrix(n_tx, n_layers, precoder)
    data_per_layer = int(nc)

    num_symbols = len(symbols)
    symbols_per_block = data_per_layer * n_layers
    num_blocks = int(np.ceil(num_symbols / symbols_per_block)) if num_symbols else 0
    if num_blocks == 0:
        return np.empty((n_tx, 0), dtype=np.complex128), 0

    layer_grid = _split_symbols_into_layers(symbols, n_layers, num_blocks, data_per_layer)
    active_grids = np.zeros((n_tx, num_blocks, nc), dtype=np.complex128)

    for block_idx in range(num_blocks):
        active_grids[:, block_idx, :] = precoder_matrix @ layer_grid[:, block_idx, :]

    time_signals = [
        _map_active_grid_to_time(active_grids[tx_idx], n_fft, nc).reshape(-1)
        for tx_idx in range(n_tx)
    ]
    return np.vstack(time_signals), num_blocks


def add_cyclic_prefix(signal, num_blocks, n_fft, cp_config):
    """Anade prefijo ciclico a cada bloque OFDM."""
    signal = np.asarray(signal, dtype=np.complex128)
    cp_lengths = _cp_lengths_for_blocks(cp_config, num_blocks, n_fft)
    blocks = signal.reshape(num_blocks, n_fft)

    with_cp = [
        np.concatenate((block[-cp_len:], block))
        for block, cp_len in zip(blocks, cp_lengths)
    ]
    return np.concatenate(with_cp), cp_lengths


def remove_cyclic_prefix(rx_signal, n_fft, cp_config):
    """Elimina el CP asumiendo sincronizacion perfecta."""
    rx_signal = np.asarray(rx_signal, dtype=np.complex128)
    rx_no_cp = []
    offset = 0
    block_idx = 0

    if np.isscalar(cp_config):
        cp_pattern = np.array([int(cp_config)], dtype=int)
    else:
        cp_pattern = np.asarray(cp_config, dtype=int)

    while offset < len(rx_signal):
        cp_len = int(cp_pattern[block_idx % len(cp_pattern)])
        block_start = offset + cp_len
        block_end = block_start + n_fft
        if block_end > len(rx_signal):
            break
        rx_no_cp.append(rx_signal[block_start:block_end])
        offset = block_end
        block_idx += 1

    if not rx_no_cp:
        return np.array([], dtype=np.complex128)
    return np.concatenate(rx_no_cp)


def _equalize_grid(active_grid, h_freq, noise_to_signal=0.0, threshold=1e-10):
    noise_to_signal = max(0.0, float(noise_to_signal))
    denom = np.abs(h_freq) ** 2 + noise_to_signal
    denom = np.maximum(denom, threshold)
    return active_grid * np.conj(h_freq) / denom


def demodulate_ofdm_with_channel(
    rx_time_signal,
    n_fft,
    nc,
    h,
    noise_to_signal=0.0,
    channel_scale=1.0,
    threshold=1e-10,
):
    """Demodula SISO usando la respuesta de canal conocida directamente."""
    active_grid = _time_to_active_grid(rx_time_signal, n_fft, nc)
    if active_grid.shape[0] == 0:
        return np.array([], dtype=np.complex128), active_grid

    h_freq = channel_frequency_response(h, n_fft, nc) * complex(channel_scale)
    equalized_grid = _equalize_grid(active_grid, h_freq[None, :], noise_to_signal, threshold)
    return equalized_grid.reshape(-1), h_freq


def _detect_mimo_layers(
    active_rx_grid,
    h_eff,
    detector,
    noise_to_signal,
    threshold,
    mod_type,
):
    """Aplica r[k] = H_eff[k] s[k] + n[k] en cada subportadora OFDM."""
    num_blocks = active_rx_grid.shape[1]
    nc = active_rx_grid.shape[2]
    if h_eff.ndim == 3:
        h_blocks = np.broadcast_to(h_eff[None, :, :, :], (num_blocks, *h_eff.shape))
    elif h_eff.ndim == 4:
        h_blocks = h_eff
    else:
        raise ValueError("El canal MIMO efectivo debe ser 3D o 4D")

    n_layers = h_blocks.shape[3]
    detected_layers = np.zeros((n_layers, num_blocks * nc), dtype=np.complex128)

    for block_idx in range(num_blocks):
        block_h = h_blocks[block_idx]
        block_y = active_rx_grid[:, block_idx, :].T
        block_detected = detect_mimo_symbols(
            block_y,
            block_h,
            detector=detector,
            noise_to_signal=noise_to_signal,
            threshold=threshold,
            mod_type=mod_type,
        )
        start = block_idx * nc
        end = start + nc
        detected_layers[:, start:end] = block_detected.T

    return detected_layers


def demodulate_mimo_ofdm_with_channel(
    rx_time_signals,
    n_fft,
    nc,
    h,
    n_tx=2,
    n_layers=None,
    precoder="identity",
    detector="MMSE",
    noise_to_signal=0.0,
    mod_type=None,
    channel_scale=1.0,
    threshold=1e-10,
):
    """Demodula MIMO usando H[k] conocida directamente desde el canal."""
    active_rx_grid = _time_to_active_grid_multi(rx_time_signals, n_fft, nc)
    if active_rx_grid.shape[1] == 0:
        return np.array([], dtype=np.complex128), active_rx_grid

    n_tx = int(n_tx)
    n_layers = n_tx if n_layers is None else int(n_layers)
    precoder_matrix = mimo_precoder_matrix(n_tx, n_layers, precoder)
    h_phys = channel_frequency_response(h, n_fft, nc)
    h_eff = effective_mimo_channel(h_phys, precoder_matrix, channel_scale)
    detected_layers = _detect_mimo_layers(
        active_rx_grid,
        h_eff,
        detector,
        noise_to_signal,
        threshold,
        mod_type,
    )
    return _interleave_layer_symbols(detected_layers), h_phys
