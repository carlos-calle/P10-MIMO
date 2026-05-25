import itertools
from functools import lru_cache

import cv2
import numpy as np

from .config import LTE_BANDWIDTHS, LTE_PROFILES, MODULATION_BITS


def get_cp_lengths(profile_idx, n_fft):
    """Devuelve el patron de CP escalado para el tamano FFT elegido."""
    profile = LTE_PROFILES[profile_idx]
    scale = n_fft / 2048
    return tuple(max(1, int(round(cp * scale))) for cp in profile["cp_ref"])


def get_ofdm_params(bw_idx, profile_idx):
    """Devuelve n_fft, subportadoras activas, patron de CP y separacion."""
    bw_cfg = LTE_BANDWIDTHS[bw_idx]
    profile = LTE_PROFILES[profile_idx]
    n_fft = bw_cfg["n_fft"]
    nc = bw_cfg["n_sc"]
    cp_lengths = get_cp_lengths(profile_idx, n_fft)
    return n_fft, nc, cp_lengths, profile["delta_f_hz"]


def image_to_bits(image_path, size):
    """Convierte una imagen a escala de grises en un flujo de bits."""
    img = cv2.imread(image_path, 0)
    if img is None:
        raise FileNotFoundError(f"No se encontro la imagen: {image_path}")
    img = cv2.resize(img, (size, size))
    bits = np.unpackbits(img)
    return bits.astype(np.uint8), img


def bits_to_image(bits, size):
    """Reconstruye una imagen cuadrada desde bits."""
    expected_len = size * size * 8
    bits = np.asarray(bits, dtype=np.uint8)
    if len(bits) < expected_len:
        bits = np.pad(bits, (0, expected_len - len(bits)))
    bits = bits[:expected_len]
    img = np.packbits(bits)
    return img.reshape((size, size))


def _bits_per_symbol(mod_type):
    try:
        return MODULATION_BITS[mod_type]
    except KeyError as exc:
        raise ValueError("Modulacion no soportada") from exc


def _lte_modulate_groups(bit_groups, mod_type):
    """Mapeo LTE de bits a simbolos, vectorizado por grupos."""
    bits = np.asarray(bit_groups, dtype=np.int16)

    if mod_type == 1:
        i = 1 - 2 * bits[:, 0]
        q = 1 - 2 * bits[:, 1]
        scale = 1 / np.sqrt(2)
    elif mod_type == 2:
        i = (1 - 2 * bits[:, 0]) * (1 + 2 * bits[:, 2])
        q = (1 - 2 * bits[:, 1]) * (1 + 2 * bits[:, 3])
        scale = 1 / np.sqrt(10)
    elif mod_type == 3:
        mag = np.array([3, 1, 5, 7], dtype=np.int16)
        i_mag = mag[bits[:, 2] * 2 + bits[:, 4]]
        q_mag = mag[bits[:, 3] * 2 + bits[:, 5]]
        i = (1 - 2 * bits[:, 0]) * i_mag
        q = (1 - 2 * bits[:, 1]) * q_mag
        scale = 1 / np.sqrt(42)
    else:
        raise ValueError("Modulacion no soportada")

    return (i + 1j * q) * scale


@lru_cache(maxsize=None)
def get_constellation_map(mod_type):
    """Devuelve el diccionario de constelacion LTE y bits por simbolo."""
    n_bits = _bits_per_symbol(mod_type)
    bit_groups = np.array(list(itertools.product((0, 1), repeat=n_bits)), dtype=np.uint8)
    symbols = _lte_modulate_groups(bit_groups, mod_type)
    return {tuple(group.tolist()): symbol for group, symbol in zip(bit_groups, symbols)}, n_bits


def map_bits_to_symbols(bits, mod_type):
    """Modulador digital LTE: bits -> simbolos complejos normalizados."""
    n_bits = _bits_per_symbol(mod_type)
    bits = np.asarray(bits, dtype=np.uint8)

    remainder = len(bits) % n_bits
    if remainder:
        bits = np.pad(bits, (0, n_bits - remainder))

    bit_groups = bits.reshape(-1, n_bits)
    return _lte_modulate_groups(bit_groups, mod_type)


def demap_symbols_to_bits(symbols, mod_type):
    """Demodulador ML vectorizado: simbolos complejos -> bits."""
    constellation, n_bits = get_constellation_map(mod_type)
    points = np.array(list(constellation.values()), dtype=np.complex128)
    bit_maps = np.array(list(constellation.keys()), dtype=np.uint8)
    symbols = np.asarray(symbols, dtype=np.complex128)

    decoded_chunks = []
    chunk_size = 65_536
    for start in range(0, len(symbols), chunk_size):
        chunk = symbols[start:start + chunk_size]
        distances = np.abs(chunk[:, None] - points[None, :]) ** 2
        nearest = np.argmin(distances, axis=1)
        decoded_chunks.append(bit_maps[nearest])

    if not decoded_chunks:
        return np.array([], dtype=np.uint8)
    return np.vstack(decoded_chunks).reshape(-1)[: len(symbols) * n_bits]


def apply_scrambling(bits, seed=2024):
    """
    Aplica o revierte scrambling aditivo con XOR.

    Al usar XOR, la misma funcion sirve para scrambling y descrambling siempre
    que se use la misma semilla.
    """
    bits = np.asarray(bits, dtype=np.uint8)
    rng = np.random.default_rng(seed)
    scrambling_sequence = rng.integers(0, 2, len(bits), dtype=np.uint8)
    return np.bitwise_xor(bits, scrambling_sequence)
