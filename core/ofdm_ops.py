import numpy as np

from .config import PILOT_SEED, PILOT_SPACING_SC


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


def pilot_subcarrier_mask(nc, pilot_spacing=PILOT_SPACING_SC):
    """Mascara de pilotos dentro de las subportadoras activas."""
    if pilot_spacing <= 0:
        raise ValueError("El espaciamiento de pilotos debe ser positivo")
    return (np.arange(nc) % pilot_spacing) == 0


def pilot_symbol_grid(num_blocks, num_pilots, seed=PILOT_SEED):
    """Secuencia QPSK deterministica conocida por Tx y Rx."""
    if num_blocks <= 0 or num_pilots <= 0:
        return np.empty((max(num_blocks, 0), max(num_pilots, 0)), dtype=np.complex128)

    rng = np.random.default_rng(seed)
    alphabet = np.array(
        [1 + 1j, 1 - 1j, -1 + 1j, -1 - 1j],
        dtype=np.complex128,
    ) / np.sqrt(2)
    return alphabet[rng.integers(0, len(alphabet), size=(num_blocks, num_pilots))]


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
    """
    Empaqueta simbolos en subportadoras centradas y aplica IFFT.

    symbols: array de simbolos complejos QPSK/QAM.
    n_fft: tamano total de FFT.
    nc: numero de subportadoras activas.
    """
    symbols = np.asarray(symbols, dtype=np.complex128)
    num_symbols = len(symbols)
    num_blocks = int(np.ceil(num_symbols / nc)) if num_symbols else 0
    if num_blocks == 0:
        return np.array([], dtype=np.complex128), 0

    padded = np.zeros(num_blocks * nc, dtype=np.complex128)
    padded[:num_symbols] = symbols
    data_grid = padded.reshape(num_blocks, nc)

    time_grid = _map_active_grid_to_time(data_grid, n_fft, nc)
    return time_grid.reshape(-1), num_blocks


def modulate_ofdm_with_pilots(
    symbols,
    n_fft,
    nc,
    pilot_spacing=PILOT_SPACING_SC,
    pilot_seed=PILOT_SEED,
):
    """
    Inserta pilotos conocidos en la grilla activa y aplica IFFT.

    El piloto se ubica cada `pilot_spacing` subportadoras activas. Los simbolos
    de datos ocupan las posiciones restantes.
    """
    symbols = np.asarray(symbols, dtype=np.complex128)
    pilot_mask = pilot_subcarrier_mask(nc, pilot_spacing)
    data_mask = ~pilot_mask
    data_per_block = int(np.sum(data_mask))
    num_symbols = len(symbols)
    num_blocks = int(np.ceil(num_symbols / data_per_block)) if num_symbols else 0
    if num_blocks == 0:
        return np.array([], dtype=np.complex128), 0

    padded = np.zeros(num_blocks * data_per_block, dtype=np.complex128)
    padded[:num_symbols] = symbols
    data_grid = padded.reshape(num_blocks, data_per_block)

    active_grid = np.zeros((num_blocks, nc), dtype=np.complex128)
    active_grid[:, pilot_mask] = pilot_symbol_grid(num_blocks, int(np.sum(pilot_mask)), pilot_seed)
    active_grid[:, data_mask] = data_grid

    time_grid = _map_active_grid_to_time(active_grid, n_fft, nc)
    return time_grid.reshape(-1), num_blocks


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


def demodulate_ofdm(rx_time_signal, n_fft, nc):
    """Aplica FFT y recupera las subportadoras activas."""
    return _time_to_active_grid(rx_time_signal, n_fft, nc).reshape(-1)


def _interpolate_channel_from_pilots(h_pilots, pilot_indices, nc):
    """Interpolacion lineal compleja de H[k] estimada en pilotos."""
    subcarrier_indices = np.arange(nc)
    h_real = np.empty((h_pilots.shape[0], nc), dtype=float)
    h_imag = np.empty((h_pilots.shape[0], nc), dtype=float)

    for block_idx, pilot_values in enumerate(h_pilots):
        h_real[block_idx] = np.interp(subcarrier_indices, pilot_indices, pilot_values.real)
        h_imag[block_idx] = np.interp(subcarrier_indices, pilot_indices, pilot_values.imag)

    return h_real + 1j * h_imag


def demodulate_ofdm_with_pilots(
    rx_time_signal,
    n_fft,
    nc,
    pilot_spacing=PILOT_SPACING_SC,
    pilot_seed=PILOT_SEED,
    threshold=1e-10,
):
    """
    Recupera datos OFDM estimando el canal a partir de pilotos conocidos.

    Retorna los simbolos de datos ecualizados y la estimacion H[k] por bloque.
    """
    active_grid = _time_to_active_grid(rx_time_signal, n_fft, nc)
    if active_grid.shape[0] == 0:
        return np.array([], dtype=np.complex128), active_grid

    pilot_mask = pilot_subcarrier_mask(nc, pilot_spacing)
    data_mask = ~pilot_mask
    pilot_indices = np.flatnonzero(pilot_mask)

    pilots = pilot_symbol_grid(active_grid.shape[0], len(pilot_indices), pilot_seed)
    h_pilots = active_grid[:, pilot_mask] / pilots
    h_est = _interpolate_channel_from_pilots(h_pilots, pilot_indices, nc)
    small = np.abs(h_est) < threshold
    h_est[small] = threshold + 0j

    equalized_grid = active_grid / h_est
    return equalized_grid[:, data_mask].reshape(-1), h_est


def equalize_channel(rx_freq_symbols, h_impulse_response, n_fft, nc, threshold=1e-10):
    """
    Ecualizador Zero-Forcing por subportadora.

    Divide Y[k] por H[k] en las mismas subportadoras activas usadas en Tx/Rx.
    """
    rx_freq_symbols = np.asarray(rx_freq_symbols, dtype=np.complex128)
    num_blocks = len(rx_freq_symbols) // nc
    if num_blocks == 0:
        return np.array([], dtype=np.complex128)

    h_freq = np.fft.fft(h_impulse_response, n_fft)
    h_data = h_freq[active_subcarrier_indices(n_fft, nc)].copy()

    small = np.abs(h_data) < threshold
    h_data[small] = threshold + 0j

    blocks = rx_freq_symbols[:num_blocks * nc].reshape(num_blocks, nc)
    return (blocks / h_data).reshape(-1)
