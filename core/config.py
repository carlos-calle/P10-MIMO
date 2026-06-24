"""Parametros LTE usados por el simulador.

El proyecto modela una cadena OFDM educativa. Estos valores mantienen la
relacion LTE basica entre ancho de canal, resource blocks, subportadoras y
prefijo ciclico, sin intentar implementar todo el grid fisico de LTE.
"""

DELTA_F_HZ = 15_000
REFERENCE_FFT_SIZE = 2048

# Indice de GUI -> parametros de ancho de banda.
# n_sc = n_rb * 12 subportadoras activas. n_fft sigue las tasas de muestreo
# LTE habituales para 15 kHz: 1.92, 3.84, 7.68, 15.36, 23.04 y 30.72 Msps.
LTE_BANDWIDTHS = {
    1: {"name": "1.4 MHz", "bandwidth_hz": 1.4e6, "n_rb": 6, "n_sc": 72, "n_fft": 128},
    2: {"name": "3 MHz", "bandwidth_hz": 3e6, "n_rb": 15, "n_sc": 180, "n_fft": 256},
    3: {"name": "5 MHz", "bandwidth_hz": 5e6, "n_rb": 25, "n_sc": 300, "n_fft": 512},
    4: {"name": "10 MHz", "bandwidth_hz": 10e6, "n_rb": 50, "n_sc": 600, "n_fft": 1024},
    5: {"name": "15 MHz", "bandwidth_hz": 15e6, "n_rb": 75, "n_sc": 900, "n_fft": 1536},
    6: {"name": "20 MHz", "bandwidth_hz": 20e6, "n_rb": 100, "n_sc": 1200, "n_fft": 2048},
}

# Longitudes de CP referidas a N=2048 y Delta_f=15 kHz.
# Normal: primer simbolo de cada slot mas largo; luego 6 simbolos con CP menor.
# Extendido: 6 simbolos por slot con CP constante.
LTE_PROFILES = {
    1: {"name": "Normal", "delta_f_hz": DELTA_F_HZ, "cp_ref": (160, 144, 144, 144, 144, 144, 144)},
    2: {"name": "Extendido", "delta_f_hz": DELTA_F_HZ, "cp_ref": (512, 512, 512, 512, 512, 512)},
}

MODULATION_NAMES = {
    1: "QPSK",
    2: "16-QAM",
    3: "64-QAM",
}

MODULATION_BITS = {
    1: 2,
    2: 4,
    3: 6,
}

MIMO_MODES = {
    1: {"name": "SISO 1x1", "n_tx": 1, "n_rx": 1, "layers": 1, "precoder": "identity"},
    2: {"name": "SM 2x2", "n_tx": 2, "n_rx": 2, "layers": 2, "precoder": "identity"},
    3: {"name": "SM 4x4", "n_tx": 4, "n_rx": 4, "layers": 4, "precoder": "identity"},
    4: {"name": "SM 4x2", "n_tx": 4, "n_rx": 2, "layers": 2, "precoder": "tx_repeat"},
    5: {"name": "SM 4x4 R2", "n_tx": 4, "n_rx": 4, "layers": 2, "precoder": "tx_repeat"},
}

MIMO_DETECTORS = {
    1: "ZF",
    2: "IRC/MMSE",
    3: "MMSE-SIC",
}

DEFAULT_MIMO_MODE = 1
DEFAULT_MIMO_DETECTOR = 2
