import numpy as np


DEFAULT_RAYLEIGH_PROFILE = "ITU Vehicular B"

CHANNEL_PROFILES = {
    "Didactico CP": {
        # Perfil no ITU: retardo elegido para quedar fuera del CP normal
        # (~4.7 us) y dentro del CP extendido (~16.7 us) con Delta_f=15 kHz.
        "delays_s": np.array([0.0, 12.0]) * 1e-6,
        "gains_db": np.array([0.0, -8.0]),
        "deterministic_coefficients": np.array([1.0 + 0j, 0.4 + 0j]),
    },
    "ITU Pedestrian A": {
        "delays_s": np.array([0.0, 0.110, 0.190, 0.410]) * 1e-6,
        "gains_db": np.array([0.0, -9.7, -19.2, -22.8]),
    },
    "ITU Pedestrian B": {
        "delays_s": np.array([0.0, 0.200, 0.800, 1.200, 2.300, 3.700]) * 1e-6,
        "gains_db": np.array([0.0, -0.9, -4.9, -8.0, -7.8, -23.9]),
    },
    "ITU Vehicular A": {
        "delays_s": np.array([0.0, 0.310, 0.710, 1.090, 1.730, 2.510]) * 1e-6,
        "gains_db": np.array([0.0, -1.0, -9.0, -10.0, -15.0, -20.0]),
    },
    "ITU Vehicular B": {
        "delays_s": np.array([0.0, 0.300, 8.900, 12.900, 17.100, 20.000]) * 1e-6,
        "gains_db": np.array([-2.5, 0.0, -12.8, -10.0, -25.2, -16.0]),
    },
}

def _as_rng(rng=None):
    return np.random.default_rng() if rng is None else rng


def get_rayleigh_profile(profile_name=DEFAULT_RAYLEIGH_PROFILE):
    """Devuelve una copia del perfil usado para construir el canal."""
    if profile_name not in CHANNEL_PROFILES:
        raise ValueError(f"Perfil Rayleigh desconocido: {profile_name}")

    profile = CHANNEL_PROFILES[profile_name]
    return {
        "delays_s": profile["delays_s"].copy(),
        "gains_db": profile["gains_db"].copy(),
    }


def describe_rayleigh_paths(
    num_taps,
    sample_rate_hz=None,
    profile_name=DEFAULT_RAYLEIGH_PROFILE,
):
    """Resume los caminos del perfil que quedan activos con el slider."""
    if num_taps <= 0:
        raise ValueError("El numero de caminos debe ser positivo")

    profile = get_rayleigh_profile(profile_name)
    path_count = min(int(num_taps), len(profile["delays_s"]))
    delays_s = profile["delays_s"][:path_count]
    gains_db = profile["gains_db"][:path_count]
    sample_delays = None
    if sample_rate_hz is not None:
        sample_delays = np.rint(delays_s * sample_rate_hz).astype(int)

    return {
        "profile_name": profile_name,
        "requested_paths": int(num_taps),
        "active_paths": path_count,
        "max_profile_paths": len(profile["delays_s"]),
        "delays_s": delays_s,
        "gains_db": gains_db,
        "sample_delays": sample_delays,
    }


def cp_safety_report(
    num_taps,
    cp_lengths,
    sample_rate_hz,
    profile_name=DEFAULT_RAYLEIGH_PROFILE,
):
    """Indica si el retardo maximo del perfil cabe dentro del CP elegido."""
    info = describe_rayleigh_paths(num_taps, sample_rate_hz, profile_name)
    cp_lengths = np.asarray(cp_lengths, dtype=int)
    max_delay = 0 if info["sample_delays"] is None else int(np.max(info["sample_delays"]))
    min_cp = int(np.min(cp_lengths)) if len(cp_lengths) else 0
    margin = min_cp - max_delay
    return {
        "profile_name": info["profile_name"],
        "max_delay_samples": max_delay,
        "min_cp_samples": min_cp,
        "margin_samples": margin,
        "isi_expected": margin < 0,
    }


def apply_awgn(signal, snr_db, rng=None, reference_power=None):
    """Anade ruido blanco gaussiano complejo segun la SNR indicada."""
    rng = _as_rng(rng)
    signal = np.asarray(signal, dtype=np.complex128)
    sig_power = np.mean(np.abs(signal) ** 2) if reference_power is None else float(reference_power)
    noise_power = sig_power / (10 ** (snr_db / 10))
    noise = np.sqrt(noise_power / 2) * (
        rng.standard_normal(len(signal)) + 1j * rng.standard_normal(len(signal))
    )
    return signal + noise


def _normalize_power_profile(power_profile):
    power_profile = np.asarray(power_profile, dtype=float)
    total_power = np.sum(power_profile)
    if total_power == 0:
        return power_profile
    return power_profile / total_power


def _generate_profile_rayleigh(num_taps, sample_rate_hz, profile_name, rng):
    profile = describe_rayleigh_paths(num_taps, sample_rate_hz, profile_name)
    path_count = profile["active_paths"]
    delays_s = profile["delays_s"]
    gains_db = profile["gains_db"]
    profile_config = CHANNEL_PROFILES[profile_name]

    if "deterministic_coefficients" in profile_config:
        coeffs = np.asarray(
            profile_config["deterministic_coefficients"][:path_count],
            dtype=np.complex128,
        )
        coeff_power = np.sum(np.abs(coeffs) ** 2)
        fading = coeffs / np.sqrt(coeff_power) if coeff_power > 0 else coeffs
        power_linear = np.ones(path_count)
    else:
        power_linear = _normalize_power_profile(10 ** (gains_db / 10.0))
        fading = (
            rng.standard_normal(path_count) + 1j * rng.standard_normal(path_count)
        ) / np.sqrt(2)

    sample_delays = profile["sample_delays"]
    h = np.zeros(int(np.max(sample_delays)) + 1, dtype=np.complex128)
    for delay, power, coeff in zip(sample_delays, power_linear, fading):
        h[int(delay)] += np.sqrt(power) * coeff

    return h


def generate_rayleigh_channel(
    num_taps=1,
    rng=None,
    sample_rate_hz=None,
    profile_name=DEFAULT_RAYLEIGH_PROFILE,
):
    """
    Genera una respuesta impulsiva SISO multipath.

    El canal se obtiene discretizando el perfil elegido con la tasa de muestreo
    OFDM, por eso `sample_rate_hz` es obligatorio.
    """
    if num_taps <= 0:
        raise ValueError("El numero de caminos debe ser positivo")
    if sample_rate_hz is None:
        raise ValueError("sample_rate_hz es obligatorio para discretizar el canal")

    rng = _as_rng(rng)
    return _generate_profile_rayleigh(num_taps, sample_rate_hz, profile_name, rng)


def apply_rayleigh(
    signal,
    snr_db,
    num_taps=1,
    h=None,
    rng=None,
    sample_rate_hz=None,
    profile_name=DEFAULT_RAYLEIGH_PROFILE,
):
    """
    Aplica canal multipath y ruido AWGN.

    Retorna la senal recibida y la respuesta al impulso h usada por el canal.
    """
    signal = np.asarray(signal, dtype=np.complex128)
    if h is None:
        h = generate_rayleigh_channel(
            num_taps,
            rng=rng,
            sample_rate_hz=sample_rate_hz,
            profile_name=profile_name,
        )
    else:
        h = np.asarray(h, dtype=np.complex128)

    tx_power = np.mean(np.abs(signal) ** 2)
    signal_convolved = np.convolve(signal, h, mode="full")[:len(signal)]
    signal_noisy = apply_awgn(signal_convolved, snr_db, rng=rng, reference_power=tx_power)
    return signal_noisy, h


def _pad_mimo_channels(channel_links):
    max_len = max(len(link) for row in channel_links for link in row)
    n_rx = len(channel_links)
    n_tx = len(channel_links[0])
    h = np.zeros((n_rx, n_tx, max_len), dtype=np.complex128)
    for rx_idx, row in enumerate(channel_links):
        for tx_idx, link in enumerate(row):
            h[rx_idx, tx_idx, : len(link)] = link
    return h


def generate_mimo_rayleigh_channel(
    n_tx=2,
    n_rx=2,
    num_taps=1,
    rng=None,
    sample_rate_hz=None,
    profile_name=DEFAULT_RAYLEIGH_PROFILE,
):
    """
    Genera una matriz de respuestas impulsivas MIMO.

    La forma devuelta es `(n_rx, n_tx, n_taps_discretos)`. Cada enlace
    TX-RX usa una realizacion Rayleigh independiente sobre el mismo perfil.
    """
    if n_tx <= 0 or n_rx <= 0:
        raise ValueError("El numero de antenas MIMO debe ser positivo")
    if num_taps <= 0:
        raise ValueError("El numero de caminos debe ser positivo")
    if sample_rate_hz is None:
        raise ValueError("sample_rate_hz es obligatorio para discretizar el canal")

    rng = _as_rng(rng)
    channel_links = [
        [
            _generate_profile_rayleigh(num_taps, sample_rate_hz, profile_name, rng)
            for _ in range(n_tx)
        ]
        for _ in range(n_rx)
    ]
    return _pad_mimo_channels(channel_links)


def apply_mimo_rayleigh(
    tx_signals,
    snr_db,
    num_taps=1,
    h=None,
    rng=None,
    sample_rate_hz=None,
    profile_name=DEFAULT_RAYLEIGH_PROFILE,
    n_rx=2,
):
    """
    Aplica canal MIMO multipath y AWGN por antena RX.

    `tx_signals` debe tener forma `(n_tx, n_muestras)`. Retorna la senal
    recibida con forma `(n_rx, n_muestras)` y la matriz de canal usada.
    """
    tx_signals = np.asarray(tx_signals, dtype=np.complex128)
    if tx_signals.ndim == 1:
        tx_signals = tx_signals[None, :]
    if tx_signals.ndim != 2:
        raise ValueError("tx_signals debe ser una matriz n_tx x muestras")

    rng = _as_rng(rng)
    n_tx, n_samples = tx_signals.shape
    if h is None:
        h = generate_mimo_rayleigh_channel(
            n_tx=n_tx,
            n_rx=n_rx,
            num_taps=num_taps,
            rng=rng,
            sample_rate_hz=sample_rate_hz,
            profile_name=profile_name,
        )
    else:
        h = np.asarray(h, dtype=np.complex128)

    if h.ndim != 3 or h.shape[1] != n_tx:
        raise ValueError("La matriz de canal MIMO no coincide con tx_signals")

    n_rx = h.shape[0]
    rx_signals = np.zeros((n_rx, n_samples), dtype=np.complex128)
    for rx_idx in range(n_rx):
        for tx_idx in range(n_tx):
            rx_signals[rx_idx] += np.convolve(
                tx_signals[tx_idx],
                h[rx_idx, tx_idx],
                mode="full",
            )[:n_samples]

    tx_power = float(np.mean(np.sum(np.abs(tx_signals) ** 2, axis=0)))
    rx_noisy = np.vstack(
        [
            apply_awgn(rx_signals[rx_idx], snr_db, rng=rng, reference_power=tx_power)
            for rx_idx in range(n_rx)
        ]
    )
    return rx_noisy, h
