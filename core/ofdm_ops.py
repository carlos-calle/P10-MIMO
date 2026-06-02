from functools import lru_cache

import numpy as np

from .config import (
    CHANNEL_ESTIMATION_RIDGE,
    PILOT_SEED,
    PILOT_SPACING_SC,
    PILOT_STAGGER_ENABLED,
    PILOT_STAGGER_OFFSET_SC,
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


def _pilot_offset(block_idx, pilot_spacing, staggered):
    if not staggered:
        return 0
    return (int(block_idx) % 2) * (PILOT_STAGGER_OFFSET_SC % pilot_spacing)


def pilot_subcarrier_mask(
    nc,
    pilot_spacing=PILOT_SPACING_SC,
    block_idx=0,
    staggered=PILOT_STAGGER_ENABLED,
):
    """Mascara de pilotos dentro de las subportadoras activas."""
    if pilot_spacing <= 0:
        raise ValueError("El espaciamiento de pilotos debe ser positivo")
    offset = _pilot_offset(block_idx, pilot_spacing, staggered)
    return ((np.arange(nc) - offset) % pilot_spacing) == 0


def pilot_subcarrier_masks(
    num_blocks,
    nc,
    pilot_spacing=PILOT_SPACING_SC,
    staggered=PILOT_STAGGER_ENABLED,
):
    """Mascara 2D de pilotos con desplazamiento alternado por bloque."""
    if num_blocks <= 0:
        return np.empty((0, nc), dtype=bool)
    return np.vstack(
        [
            pilot_subcarrier_mask(nc, pilot_spacing, block_idx, staggered)
            for block_idx in range(num_blocks)
        ]
    )


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


def modulate_ofdm_with_pilots(
    symbols,
    n_fft,
    nc,
    pilot_spacing=PILOT_SPACING_SC,
    pilot_seed=PILOT_SEED,
    pilot_staggered=PILOT_STAGGER_ENABLED,
):
    """
    Inserta pilotos conocidos en la grilla activa y aplica IFFT.

    El piloto se ubica cada `pilot_spacing` subportadoras activas. Si el
    patron escalonado esta activo, los bloques alternan un desplazamiento de
    media separacion para densificar la estimacion en frecuencia.
    """
    symbols = np.asarray(symbols, dtype=np.complex128)
    first_pilot_mask = pilot_subcarrier_mask(nc, pilot_spacing, 0, pilot_staggered)
    data_per_block = nc - int(np.sum(first_pilot_mask))
    num_symbols = len(symbols)
    num_blocks = int(np.ceil(num_symbols / data_per_block)) if num_symbols else 0
    if num_blocks == 0:
        return np.array([], dtype=np.complex128), 0

    pilot_masks = pilot_subcarrier_masks(num_blocks, nc, pilot_spacing, pilot_staggered)
    pilot_counts = np.sum(pilot_masks, axis=1)
    if not np.all(pilot_counts == pilot_counts[0]):
        raise ValueError("El patron de pilotos debe mantener el mismo overhead por bloque")

    padded = np.zeros(num_blocks * data_per_block, dtype=np.complex128)
    padded[:num_symbols] = symbols
    data_grid = padded.reshape(num_blocks, data_per_block)

    active_grid = np.zeros((num_blocks, nc), dtype=np.complex128)
    pilots = pilot_symbol_grid(num_blocks, int(pilot_counts[0]), pilot_seed)
    for block_idx in range(num_blocks):
        pilot_mask = pilot_masks[block_idx]
        active_grid[block_idx, pilot_mask] = pilots[block_idx]
        active_grid[block_idx, ~pilot_mask] = data_grid[block_idx]

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


def _average_pilot_observations(active_grid, pilot_masks, pilots, nc):
    sum_h = np.zeros(nc, dtype=np.complex128)
    count_h = np.zeros(nc, dtype=int)

    for block_idx, pilot_mask in enumerate(pilot_masks):
        pilot_indices = np.flatnonzero(pilot_mask)
        h_ls = active_grid[block_idx, pilot_mask] / pilots[block_idx]
        sum_h[pilot_indices] += h_ls
        count_h[pilot_indices] += 1

    known_indices = np.flatnonzero(count_h > 0)
    if len(known_indices) == 0:
        return known_indices, np.array([], dtype=np.complex128)
    return known_indices, sum_h[known_indices] / count_h[known_indices]


@lru_cache(maxsize=32)
def _time_domain_ls_weights(n_fft, nc, tap_count, known_indices_tuple, ridge):
    active_bins = active_subcarrier_indices(n_fft, nc)
    known_indices = np.asarray(known_indices_tuple, dtype=int)
    pilot_bins = active_bins[known_indices]
    taps = np.arange(tap_count)
    basis = np.exp(-2j * np.pi * pilot_bins[:, None] * taps[None, :] / n_fft)
    if ridge > 0:
        gram = basis.conj().T @ basis
        return np.linalg.solve(gram + ridge * np.eye(tap_count), basis.conj().T)
    return np.linalg.pinv(basis)


def _estimate_channel_from_time_domain_ls(
    active_grid,
    pilot_masks,
    pilots,
    n_fft,
    nc,
    max_channel_taps,
    ridge,
):
    """Estima taps del canal desde pilotos y reconstruye H[k] por FFT."""
    known_indices, h_known = _average_pilot_observations(active_grid, pilot_masks, pilots, nc)
    if len(known_indices) == 0:
        return np.ones_like(active_grid, dtype=np.complex128)

    tap_count = min(max(1, int(max_channel_taps)), n_fft, len(known_indices))
    weights = _time_domain_ls_weights(
        n_fft,
        nc,
        tap_count,
        tuple(known_indices.tolist()),
        float(ridge),
    )
    h_taps = weights @ h_known
    h_time = np.zeros(n_fft, dtype=np.complex128)
    h_time[:tap_count] = h_taps
    h_active = np.fft.fft(h_time)[active_subcarrier_indices(n_fft, nc)]
    return np.tile(h_active, (active_grid.shape[0], 1))


def _equalize_grid(active_grid, h_est, noise_to_signal=0.0, threshold=1e-10):
    noise_to_signal = max(0.0, float(noise_to_signal))
    denom = np.abs(h_est) ** 2 + noise_to_signal
    denom[denom < threshold] = threshold
    return active_grid * np.conj(h_est) / denom


def demodulate_ofdm_with_pilots(
    rx_time_signal,
    n_fft,
    nc,
    max_channel_taps,
    noise_to_signal=0.0,
    pilot_spacing=PILOT_SPACING_SC,
    pilot_seed=PILOT_SEED,
    pilot_staggered=PILOT_STAGGER_ENABLED,
    channel_estimation_ridge=CHANNEL_ESTIMATION_RIDGE,
    threshold=1e-10,
):
    """
    Recupera datos OFDM estimando el canal a partir de pilotos conocidos.

    Retorna los simbolos de datos ecualizados y la estimacion H[k] por bloque.
    """
    active_grid = _time_to_active_grid(rx_time_signal, n_fft, nc)
    if active_grid.shape[0] == 0:
        return np.array([], dtype=np.complex128), active_grid

    num_blocks = active_grid.shape[0]
    pilot_masks = pilot_subcarrier_masks(num_blocks, nc, pilot_spacing, pilot_staggered)
    pilot_counts = np.sum(pilot_masks, axis=1)
    if not np.all(pilot_counts == pilot_counts[0]):
        raise ValueError("El patron de pilotos debe mantener el mismo overhead por bloque")

    pilots = pilot_symbol_grid(num_blocks, int(pilot_counts[0]), pilot_seed)
    h_est = _estimate_channel_from_time_domain_ls(
        active_grid,
        pilot_masks,
        pilots,
        n_fft,
        nc,
        max_channel_taps,
        channel_estimation_ridge,
    )

    equalized_grid = _equalize_grid(
        active_grid,
        h_est,
        noise_to_signal,
        threshold,
    )
    data_blocks = [
        equalized_grid[block_idx, ~pilot_masks[block_idx]]
        for block_idx in range(num_blocks)
    ]
    return np.concatenate(data_blocks), h_est
