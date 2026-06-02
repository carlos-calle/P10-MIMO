# Partes importantes del simulador

Este documento resume las partes mas importantes del simulador LTE-OFDM,
indicando en que archivo estan, que hacen y que fragmentos de codigo conviene
reconocer para explicarlo.

## Mapa rapido

```text
main.py
    Arranca la aplicacion.

ui/main_window.py
    Interfaz grafica, botones, pestanas, sliders, graficas y worker thread.

controller/simulation_mgr.py
    Coordina la simulacion completa: imagen, OFDM, canal, BER y PAPR.

core/config.py
    Parametros LTE: anchos de banda, FFT, CP, modulaciones y pilotos.

core/utils.py
    Imagen a bits, bits a imagen, scrambling, modulacion y demodulacion digital.

core/ofdm_ops.py
    Operaciones OFDM: subportadoras, pilotos, IFFT/FFT, CP y ecualizacion.

core/channel.py
    Canal Rayleigh multipath, AWGN y reporte de margen del prefijo ciclico.

tests/test_core.py
    Pruebas automaticas del nucleo y del controlador.
```

## 1. Arranque del programa

Archivo: `main.py`

Esta es la entrada del proyecto. Su unica responsabilidad importante es crear
la ventana principal e iniciar el loop de la aplicacion.

```python
from ui.main_window import MainWindow

if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
```

La simulacion no se implementa aqui. `main.py` solo conecta con la interfaz.

## 2. Interfaz grafica

Archivo: `ui/main_window.py`

La clase principal es:

```python
class MainWindow(ctk.CTk):
```

Esta clase construye la ventana con CustomTkinter. Aqui se definen:

- selector de ancho de banda;
- selector de prefijo ciclico;
- selector de modulacion;
- slider de SNR;
- slider de caminos multipath;
- boton para seleccionar imagen;
- boton para transmitir imagen;
- boton para curva BER;
- boton para PAPR;
- pestanas de imagen, BER y PAPR.

### Seleccion de imagen

Funcion: `select_file`

```python
file_path = filedialog.askopenfilename(
    title="Seleccionar Imagen",
    filetypes=[("Archivos de Imagen", "*.jpg *.jpeg *.png *.bmp")]
)

if file_path:
    self.selected_image_path = file_path
```

Aqui todavia no se procesa la imagen. Solo se guarda la ruta para usarla luego.

### Ejecucion en segundo plano

Funcion: `_start_worker`

Las simulaciones pesadas se mandan a un hilo secundario para que la interfaz no
se congele.

```python
def worker_target():
    try:
        result = target(*args)
        self.worker_queue.put(("success", task_name, result))
    except Exception as exc:
        self.worker_queue.put(("error", task_name, str(exc)))

self.worker_thread = threading.Thread(
    target=worker_target,
    name=f"ofdm-{task_name}-worker",
    daemon=True,
)
self.worker_thread.start()
```

La GUI no calcula directamente OFDM, BER ni PAPR. La GUI llama al controlador y
espera el resultado por una cola.

### Transmitir imagen

Funcion: `action_run_image`

Cuando se pulsa `TRANSMITIR IMAGEN`, se leen los parametros de la GUI y se llama
a `run_image_transmission`.

```python
bw_idx = self.bw_map[self.option_bw.get()]
prof_idx = self.cp_map[self.option_cp.get()]
mod_idx = self.mod_map[self.option_mod.get()]
snr = int(self.slider_snr.get())
paths = int(self.slider_paths.get())

self._start_worker(
    "image",
    "Procesando OFDM...",
    self.manager.run_image_transmission,
    (self.selected_image_path, bw_idx, prof_idx, mod_idx, snr, paths),
    self._show_image_result,
)
```

### Generar BER

Funcion: `action_plot_ber`

```python
self._start_worker(
    "ber",
    "Calculando BER Monte Carlo de la imagen...",
    self.manager.calculate_ber_curve,
    (self.selected_image_path, bw_idx, prof_idx, None, paths),
    self._show_ber_result,
)
```

Aunque la GUI tenga una modulacion seleccionada, la curva BER compara siempre
QPSK, 16-QAM y 64-QAM.

### Analizar PAPR

Funcion: `action_plot_papr`

```python
self._start_worker(
    "papr",
    "Calculando PAPR de la imagen para 3 modulaciones...",
    self.manager.calculate_papr_distribution,
    (self.selected_image_path, bw_idx, prof_idx),
    self._show_papr_result,
)
```

PAPR tambien compara las tres modulaciones.

## 3. Controlador principal de simulacion

Archivo: `controller/simulation_mgr.py`

La clase central es:

```python
class OFDMSimulationManager:
```

Su constructor define parametros globales del experimento:

```python
self.img_size = 250
self.mc_min_runs = 5
self.mc_max_runs = 25
self.mc_confidence_z = 1.96
self.mc_abs_ci_target = 2e-4
self.mc_rel_ci_target = 0.25
self.mc_seed = 2024
self.papr_oversampling = 4
```

Puntos importantes:

- `img_size = 250`: toda imagen se procesa como `250x250`.
- `mc_confidence_z = 1.96`: intervalos de confianza aproximados al 95%.
- `papr_oversampling = 4`: PAPR usa IFFT sobremuestreada con `4 * n_fft`.

## 4. Transmision completa de imagen

Archivo: `controller/simulation_mgr.py`

Funcion: `run_image_transmission`

Esta es una de las funciones mas importantes. Ejecuta la cadena completa:

```text
imagen -> bits -> scrambling -> modulacion -> OFDM -> CP
       -> canal Rayleigh + AWGN -> quitar CP -> FFT
       -> estimacion de canal -> demapeo -> descrambling
       -> imagen recibida + BER
```

Fragmento clave:

```python
n_fft, nc, cp_lengths, df = utils.get_ofdm_params(bw_idx, profile_idx)
sample_rate_hz = n_fft * df
channel_report = channel.cp_safety_report(num_paths, cp_lengths, sample_rate_hz)

tx_bits_raw, tx_img_matrix = utils.image_to_bits(image_path, img_size)
tx_bits = utils.apply_scrambling(tx_bits_raw)
tx_symbols = utils.map_bits_to_symbols(tx_bits, mod_type)

ofdm_time_signal, num_blocks = ofdm_ops.modulate_ofdm_with_pilots(
    tx_symbols, n_fft, nc
)
tx_signal_cp, cp_used = ofdm_ops.add_cyclic_prefix(
    ofdm_time_signal, num_blocks, n_fft, cp_lengths
)
```

Aqui se prepara la senal transmitida. Luego pasa por el canal:

```python
rx_signal_cp, _ = channel.apply_rayleigh(
    tx_signal_cp,
    snr_db,
    num_taps=num_paths,
    sample_rate_hz=sample_rate_hz,
    rng=rng,
)
```

Y despues se recupera:

```python
rx_signal_no_cp = ofdm_ops.remove_cyclic_prefix(rx_signal_cp, n_fft, cp_used)
rx_symbols_equalized, _ = ofdm_ops.demodulate_ofdm_with_pilots(
    rx_signal_no_cp,
    n_fft,
    nc,
    max_channel_taps=len(h_used),
    noise_to_signal=10 ** (-snr_db / 10),
)
rx_bits_scrambled = utils.demap_symbols_to_bits(rx_symbols_equalized, mod_type)
rx_bits = utils.apply_scrambling(rx_bits_scrambled)
```

Finalmente se calcula BER y se reconstruye la imagen:

```python
bit_errors = np.sum(tx_bits_raw != rx_bits)
ber = bit_errors / valid_len
rx_img_matrix = utils.bits_to_image(rx_bits, img_size)
```

## 5. Calculo de BER

Archivo: `controller/simulation_mgr.py`

Funcion principal: `calculate_ber_curve`

Esta funcion calcula BER vs SNR para las tres modulaciones:

```python
snr_range = np.linspace(0, 30, 10)
tx_bits_raw, _ = utils.image_to_bits(image_path, self.img_size)

series = [
    self._calculate_ber_series(
        tx_bits_raw, bw_idx, profile_idx, current_mod, num_paths, snr_range
    )
    for current_mod in (1, 2, 3)
]
```

Cada `current_mod` representa:

```text
1 -> QPSK
2 -> 16-QAM
3 -> 64-QAM
```

La funcion devuelve un diccionario que la GUI usa para graficar:

```python
return {
    "x": snr_range,
    "series": series,
    "confidence": 0.95,
    "run_min": min_runs,
    "run_max": max_runs,
    "summary": f"BER Monte Carlo: 3 modulaciones, ...",
}
```

### Serie BER por modulacion

Funcion: `_calculate_ber_series`

Esta funcion ejecuta varias corridas Monte Carlo para una modulacion y todos
los puntos SNR.

Idea principal:

```python
for run_idx in range(self.mc_max_runs):
    scramble_seed = self.mc_seed + run_idx
    rng = np.random.default_rng(self.mc_seed * 10 + run_idx)
    tx_cp, cp_used, n_fft, nc, sample_rate_hz = self._prepare_tx_signal(...)
    h_run = channel.generate_rayleigh_channel(...)

    for idx, snr in enumerate(snr_range):
        rx_cp, h = channel.apply_rayleigh(tx_cp, snr, h=h_run, rng=rng)
        rx_bits = self._receive_bits(...)
        errors = int(np.sum(tx_bits_raw != rx_bits[:valid_len]))
```

Por cada SNR acumula:

- errores de bits;
- bits totales;
- cantidad de corridas;
- BER por corrida.

### Intervalos de confianza

Funciones: `_wilson_interval`, `_mean_interval`, `_combined_interval`

Estas funciones calculan la banda sombreada de la grafica BER.

```python
def _combined_interval(values, successes, total, z=1.96):
    wilson_low, wilson_high = _wilson_interval(successes, total, z)
    mean_low, mean_high = _mean_interval(values, z)
    return min(wilson_low, mean_low), max(wilson_high, mean_high)
```

El intervalo combinado toma el rango mas conservador entre:

- proporcion acumulada de errores de bit;
- variacion de BER entre corridas Monte Carlo.

## 6. Calculo de PAPR

Archivo: `controller/simulation_mgr.py`

Funcion principal: `calculate_papr_distribution`

El PAPR se calcula antes del canal y antes del CP. Se compara QPSK, 16-QAM y
64-QAM.

```python
tx_bits_raw, _ = utils.image_to_bits(image_path, self.img_size)
series = [
    self._calculate_papr_series(tx_bits_raw, bw_idx, profile_idx, current_mod)
    for current_mod in (1, 2, 3)
]
```

Luego se forman los umbrales de la CCDF:

```python
max_papr = max(float(np.max(item["papr_values"])) for item in series if item["total_blocks"] > 0)
thresholds = np.linspace(0, max(12, np.ceil(max_papr) + 1), 120)
```

Y se calcula:

```python
exceed_counts = np.sum(papr_values[:, None] > thresholds[None, :], axis=0)
item["y"] = exceed_counts / len(papr_values)
```

Eso implementa:

```text
CCDF(gamma) = P(PAPR > gamma)
```

### PAPR por bloque OFDM

Funcion: `_calculate_papr_values`

Esta funcion toma simbolos modulados y calcula el PAPR de cada bloque OFDM.

Primero arma pilotos y datos:

```python
pilot_mask = ofdm_ops.pilot_subcarrier_mask(nc)
data_mask = ~pilot_mask
data_per_block = int(np.sum(data_mask))
```

Luego arma la grilla activa:

```python
active_grid = np.zeros((num_blocks, nc), dtype=np.complex128)
active_grid[:, pilot_mask] = ofdm_ops.pilot_symbol_grid(
    num_blocks, int(np.sum(pilot_mask))
)
active_grid[:, data_mask] = data_grid
```

Despues sobremuestrea la senal para medir mejor los picos:

```python
os_fft = n_fft * self.papr_oversampling
freq_grid = np.zeros((num_blocks, os_fft), dtype=np.complex128)
freq_grid[:, ofdm_ops.active_subcarrier_indices(os_fft, nc)] = active_grid
time_grid = np.fft.ifft(freq_grid, axis=1) * np.sqrt(os_fft)
```

Finalmente calcula PAPR:

```python
power = np.abs(time_grid) ** 2
avg_pwr = np.mean(power, axis=1)
valid = avg_pwr > 0
return 10 * np.log10(np.max(power[valid], axis=1) / avg_pwr[valid])
```

La salida es una lista de PAPR en dB, uno por bloque OFDM.

## 7. Parametros LTE del simulador

Archivo: `core/config.py`

Aqui estan las tablas base del sistema.

### Anchos de banda

```python
LTE_BANDWIDTHS = {
    1: {"name": "1.4 MHz", "bandwidth_hz": 1.4e6, "n_rb": 6, "n_sc": 72, "n_fft": 128},
    2: {"name": "3 MHz", "bandwidth_hz": 3e6, "n_rb": 15, "n_sc": 180, "n_fft": 256},
    3: {"name": "5 MHz", "bandwidth_hz": 5e6, "n_rb": 25, "n_sc": 300, "n_fft": 512},
    4: {"name": "10 MHz", "bandwidth_hz": 10e6, "n_rb": 50, "n_sc": 600, "n_fft": 1024},
    5: {"name": "15 MHz", "bandwidth_hz": 15e6, "n_rb": 75, "n_sc": 900, "n_fft": 1536},
    6: {"name": "20 MHz", "bandwidth_hz": 20e6, "n_rb": 100, "n_sc": 1200, "n_fft": 2048},
}
```

### Prefijo ciclico

```python
LTE_PROFILES = {
    1: {"name": "Normal", "delta_f_hz": DELTA_F_HZ, "cp_ref": (160, 144, 144, 144, 144, 144, 144)},
    2: {"name": "Extendido", "delta_f_hz": DELTA_F_HZ, "cp_ref": (512, 512, 512, 512, 512, 512)},
}
```

El CP se define respecto a FFT 2048 y luego se escala segun el `n_fft`
seleccionado.

### Modulaciones

```python
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
```

## 8. Utilidades de imagen, bits y modulacion

Archivo: `core/utils.py`

### Parametros OFDM

Funcion: `get_ofdm_params`

```python
def get_ofdm_params(bw_idx, profile_idx):
    bw_cfg = LTE_BANDWIDTHS[bw_idx]
    profile = LTE_PROFILES[profile_idx]
    n_fft = bw_cfg["n_fft"]
    nc = bw_cfg["n_sc"]
    cp_lengths = get_cp_lengths(profile_idx, n_fft)
    return n_fft, nc, cp_lengths, profile["delta_f_hz"]
```

Devuelve:

- `n_fft`: tamano FFT.
- `nc`: subportadoras activas.
- `cp_lengths`: patron de CP.
- `delta_f_hz`: separacion de subportadoras.

### Imagen a bits

Funcion: `image_to_bits`

```python
img = cv2.imread(image_path, 0)
img = cv2.resize(img, (size, size))
bits = np.unpackbits(img)
return bits.astype(np.uint8), img
```

La imagen se lee en escala de grises, se redimensiona a `250x250` y se convierte
a bits.

### Bits a imagen

Funcion: `bits_to_image`

```python
bits = bits[:expected_len]
img = np.packbits(bits)
return img.reshape((size, size))
```

Convierte los bits recibidos otra vez a una matriz de pixeles.

### Scrambling

Funcion: `apply_scrambling`

```python
rng = np.random.default_rng(seed)
scrambling_sequence = rng.integers(0, 2, len(bits), dtype=np.uint8)
return np.bitwise_xor(bits, scrambling_sequence)
```

Usa XOR. Por eso la misma funcion sirve para scrambling y descrambling si se
usa la misma semilla.

### Mapeo de bits a simbolos

Funcion: `map_bits_to_symbols`

```python
n_bits = _bits_per_symbol(mod_type)
remainder = len(bits) % n_bits
if remainder:
    bits = np.pad(bits, (0, n_bits - remainder))

bit_groups = bits.reshape(-1, n_bits)
return _lte_modulate_groups(bit_groups, mod_type)
```

Agrupa los bits segun la modulacion:

- QPSK: 2 bits por simbolo.
- 16-QAM: 4 bits por simbolo.
- 64-QAM: 6 bits por simbolo.

### Demapeo de simbolos a bits

Funcion: `demap_symbols_to_bits`

```python
distances = np.abs(chunk[:, None] - points[None, :]) ** 2
nearest = np.argmin(distances, axis=1)
decoded_chunks.append(bit_maps[nearest])
```

Compara cada simbolo recibido contra todos los puntos de la constelacion y
elige el mas cercano.

## 9. Operaciones OFDM

Archivo: `core/ofdm_ops.py`

### Subportadoras activas

Funcion: `active_subcarrier_indices`

```python
half = nc // 2
negative = np.arange(n_fft - half, n_fft)
positive = np.arange(1, half + 1)
return np.concatenate((negative, positive))
```

Ubica subportadoras activas alrededor de DC y deja DC vacia.

### Mascara de pilotos

Funcion: `pilot_subcarrier_mask`

```python
offset = _pilot_offset(block_idx, pilot_spacing, staggered)
return ((np.arange(nc) - offset) % pilot_spacing) == 0
```

Marca una subportadora piloto cada 6 subportadoras activas. En bloques alternos
desplaza el patron 3 subportadoras para densificar la malla efectiva.

### Pilotos deterministas

Funcion: `pilot_symbol_grid`

```python
alphabet = np.array(
    [1 + 1j, 1 - 1j, -1 + 1j, -1 - 1j],
    dtype=np.complex128,
) / np.sqrt(2)
return alphabet[rng.integers(0, len(alphabet), size=(num_blocks, num_pilots))]
```

Genera pilotos QPSK conocidos por transmisor y receptor.

### OFDM con pilotos

Funcion: `modulate_ofdm_with_pilots`

```python
active_grid = np.zeros((num_blocks, nc), dtype=np.complex128)
for block_idx in range(num_blocks):
    pilot_mask = pilot_masks[block_idx]
    active_grid[block_idx, pilot_mask] = pilots[block_idx]
    active_grid[block_idx, ~pilot_mask] = data_grid[block_idx]

time_grid = _map_active_grid_to_time(active_grid, n_fft, nc)
return time_grid.reshape(-1), num_blocks
```

Arma la grilla frecuencia-tiempo de OFDM, inserta pilotos y aplica IFFT.

### Prefijo ciclico

Funcion: `add_cyclic_prefix`

```python
with_cp = [
    np.concatenate((block[-cp_len:], block))
    for block, cp_len in zip(blocks, cp_lengths)
]
return np.concatenate(with_cp), cp_lengths
```

Copia el final de cada bloque OFDM y lo pega al inicio.

Funcion: `remove_cyclic_prefix`

```python
block_start = offset + cp_len
block_end = block_start + n_fft
rx_no_cp.append(rx_signal[block_start:block_end])
```

En recepcion elimina el CP y conserva solo el bloque OFDM util.

### Demodulacion con pilotos

Funcion: `demodulate_ofdm_with_pilots`

```python
active_grid = _time_to_active_grid(rx_time_signal, n_fft, nc)
known_indices, h_known = _average_pilot_observations(active_grid, pilot_masks, pilots, nc)
h_taps = weights @ h_known
h_est = np.tile(h_active, (active_grid.shape[0], 1))
denom = np.abs(h_est) ** 2 + noise_to_signal
equalized_grid = active_grid * np.conj(h_est) / denom
return np.concatenate(data_blocks), h_est
```

Esta parte:

1. aplica FFT;
2. extrae pilotos recibidos;
3. estima el canal con LS sobre pilotos;
4. reconstruye la respuesta en frecuencia con un ajuste DFT/LS regularizado;
5. ecualiza las subportadoras;
6. devuelve solo los datos.

## 10. Canal Rayleigh y AWGN

Archivo: `core/channel.py`

### Perfiles de canal

El perfil por defecto es:

```python
DEFAULT_RAYLEIGH_PROFILE = "ITU Pedestrian A"
```

Tambien existe un perfil didactico para pruebas de CP:

```python
"Didactico CP": {
    "delays_s": np.array([0.0, 12.0]) * 1e-6,
    "gains_db": np.array([0.0, -8.0]),
    "deterministic_coefficients": np.array([1.0 + 0j, 0.4 + 0j]),
}
```

Este perfil no es ITU. Se usa en pruebas controladas para mostrar que el CP
normal queda corto frente a un eco de `12 us`, mientras que el CP extendido si
lo cubre.

### Reporte del CP

Funcion: `cp_safety_report`

```python
max_delay = int(np.max(info["sample_delays"]))
min_cp = int(np.min(cp_lengths))
margin = min_cp - max_delay
```

Indica si el retardo maximo del canal cabe dentro del prefijo ciclico.

### Ruido AWGN

Funcion: `apply_awgn`

```python
sig_power = np.mean(np.abs(signal) ** 2)
noise_power = sig_power / (10 ** (snr_db / 10))
noise = np.sqrt(noise_power / 2) * (
    rng.standard_normal(len(signal)) + 1j * rng.standard_normal(len(signal))
)
return signal + noise
```

Calcula la potencia de ruido a partir de la SNR y suma ruido complejo.

### Canal Rayleigh

Funcion: `apply_rayleigh`

```python
signal_convolved = np.convolve(signal, h, mode="full")[:len(signal)]
signal_noisy = apply_awgn(signal_convolved, snr_db, rng=rng, reference_power=tx_power)
return signal_noisy, h
```

Primero convoluciona la senal con la respuesta impulsiva del canal y luego
agrega ruido AWGN.

## 11. Pruebas automaticas

Archivo: `tests/test_core.py`

Las pruebas validan que el nucleo funcione correctamente.

Partes importantes:

- `test_lte_ofdm_params`: revisa FFT, subportadoras y CP.
- `test_lte_constellation_reference_points`: revisa puntos de constelacion.
- `test_modulation_roundtrip`: bits -> simbolos -> bits.
- `test_scrambling_roundtrip`: scrambling y descrambling.
- `test_ofdm_roundtrip_with_variable_cp`: OFDM con CP sin canal.
- `test_ofdm_roundtrip_with_pilot_channel_estimation`: pilotos y estimacion.
- `test_rayleigh_profile_channel_is_discrete_and_average_normalized`: canal.
- `test_manager_smoke`: transmision completa de imagen.
- `test_analysis_curves_return_expected_series`: BER y PAPR.

Se ejecutan con:

```bash
venv/bin/python -m unittest discover -v
```

## 12. Flujo completo resumido

### Transmision de imagen

```text
GUI selecciona parametros
    -> controller/simulation_mgr.py
    -> image_to_bits
    -> apply_scrambling
    -> map_bits_to_symbols
    -> modulate_ofdm_with_pilots
    -> add_cyclic_prefix
    -> apply_rayleigh
    -> remove_cyclic_prefix
    -> demodulate_ofdm_with_pilots
    -> demap_symbols_to_bits
    -> apply_scrambling
    -> bits_to_image
    -> BER + imagen recibida
```

### Curva BER

```text
Imagen cargada
    -> QPSK, 16-QAM, 64-QAM
    -> SNR de 0 a 30 dB
    -> varias corridas Monte Carlo por punto
    -> BER acumulada
    -> intervalo de confianza
    -> grafica BER vs SNR
```

### Curva PAPR

```text
Imagen cargada
    -> QPSK, 16-QAM, 64-QAM
    -> bloques OFDM con pilotos
    -> zero-padding en frecuencia
    -> IFFT de 4 * n_fft
    -> potencia maxima / potencia promedio por bloque
    -> CCDF: P(PAPR > umbral)
```

## 13. Idea principal para explicar el proyecto

El simulador esta separado en tres niveles:

```text
ui/
    Lo que ve y controla el usuario.

controller/
    El experimento completo y los resultados.

core/
    Las operaciones matematicas reutilizables.
```

La interfaz no implementa OFDM. El controlador no dibuja directamente la GUI. El
nucleo no sabe nada de botones ni ventanas. Esa separacion permite probar el
procesamiento numerico de forma independiente y mantener el proyecto mas claro.
