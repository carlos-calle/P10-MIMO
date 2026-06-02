# Flujo completo de la imagen en el simulador

Este documento explica que ocurre con una imagen desde que se selecciona en la interfaz hasta que se reconstruye en recepcion. Tambien indica en que archivo y funcion vive cada etapa.

## 1. Arranque de la aplicacion

Archivo: `main.py`

El programa inicia creando la ventana principal:

```python
from ui.main_window import MainWindow

app = MainWindow()
app.mainloop()
```

La ventana esta definida en `ui/main_window.py`, clase `MainWindow`.

## 2. Seleccion de imagen

Archivo: `ui/main_window.py`  
Funcion: `select_file`

La interfaz abre un selector de archivos y guarda la ruta seleccionada:

```python
file_path = filedialog.askopenfilename(
    title="Seleccionar Imagen",
    filetypes=[("Archivos de Imagen", "*.jpg *.jpeg *.png *.bmp")]
)

if file_path:
    self.selected_image_path = file_path
```

En este punto la imagen todavia no se procesa. Solo se guarda su ruta en:

```python
self.selected_image_path
```

## 3. Inicio de transmision

Archivo: `ui/main_window.py`  
Funcion: `action_run_image`

Cuando se pulsa `TRANSMITIR IMAGEN`, la interfaz lee los parametros seleccionados:

```python
bw_idx = self.bw_map[self.option_bw.get()]
prof_idx = self.cp_map[self.option_cp.get()]
mod_idx = self.mod_map[self.option_mod.get()]
snr = int(self.slider_snr.get())
paths = int(self.slider_paths.get())
```

Luego lanza el trabajo en un hilo secundario:

```python
self._start_worker(
    "image",
    "Procesando OFDM...",
    self.manager.run_image_transmission,
    (self.selected_image_path, bw_idx, prof_idx, mod_idx, snr, paths),
    self._show_image_result,
)
```

El controlador es la clase `OFDMSimulationManager`, ubicada en `controller/simulation_mgr.py`.
El resultado vuelve a la interfaz mediante una cola (`queue`) y se muestra en
`_show_image_result`, ya en el hilo principal de CustomTkinter.

## 4. Obtencion de parametros OFDM/LTE

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

Primero se obtienen los parametros fisicos:

```python
n_fft, nc, cp_lengths, df = utils.get_ofdm_params(bw_idx, profile_idx)
```

La funcion `get_ofdm_params` esta en `core/utils.py`.

Archivo: `core/utils.py`  
Funcion: `get_ofdm_params`

```python
bw_cfg = LTE_BANDWIDTHS[bw_idx]
profile = LTE_PROFILES[profile_idx]
n_fft = bw_cfg["n_fft"]
nc = bw_cfg["n_sc"]
cp_lengths = get_cp_lengths(profile_idx, n_fft)
return n_fft, nc, cp_lengths, profile["delta_f_hz"]
```

Los datos base salen de `core/config.py`.

## 5. Tamanos FFT usados

Archivo: `core/config.py`  
Variable: `LTE_BANDWIDTHS`

El simulador usa estos tamanos:

| Ancho de banda | RB | Subportadoras activas | FFT usada |
| --- | ---: | ---: | ---: |
| 1.4 MHz | 6 | 72 | 128 |
| 3 MHz | 15 | 180 | 256 |
| 5 MHz | 25 | 300 | 512 |
| 10 MHz | 50 | 600 | 1024 |
| 15 MHz | 75 | 900 | 1536 |
| 20 MHz | 100 | 1200 | 2048 |

Para 5 MHz, por ejemplo, hay 300 subportadoras activas y se usa FFT de 512. Para 10 MHz hay 600 subportadoras activas y se usa FFT de 1024.

La excepcion importante es 15 MHz: se usa `1536`, no `1024`. Esto es intencional para mantener los tamanos LTE-like asociados a las tasas de muestreo usuales. `1536` no es potencia de dos pura, pero es un tamano eficiente de FFT de radix mixto (`1536 = 3 * 512`). Si se quisiera un simulador estrictamente didactico de FFT radix-2, 900 subportadoras activas se podrian meter en una FFT de 1024, pero eso se alejaria del perfil LTE usado aqui.

## 6. Lectura y preprocesamiento de imagen

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

El controlador fija el tamano de imagen:

```python
img_size = self.img_size
```

Actualmente `self.img_size = 250`, definido en el constructor:

```python
def __init__(self):
    self.img_size = 250
```

Luego llama:

```python
tx_bits_raw, tx_img_matrix = utils.image_to_bits(image_path, img_size)
```

Archivo: `core/utils.py`  
Funcion: `image_to_bits`

```python
img = cv2.imread(image_path, 0)
if img is None:
    raise FileNotFoundError(f"No se encontro la imagen: {image_path}")
img = cv2.resize(img, (size, size))
bits = np.unpackbits(img)
return bits.astype(np.uint8), img
```

Aqui pasan tres cosas:

1. `cv2.imread(image_path, 0)` lee la imagen en escala de grises.
2. `cv2.resize(img, (size, size))` la redimensiona a `250x250`.
3. `np.unpackbits(img)` convierte cada pixel de 8 bits en bits individuales.

Una imagen de `250x250` produce:

```text
250 * 250 * 8 = 500000 bits
```

`tx_img_matrix` se conserva para mostrar la imagen transmitida en la interfaz.

## 7. Scrambling

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

```python
tx_bits = utils.apply_scrambling(tx_bits_raw)
```

Archivo: `core/utils.py`  
Funcion: `apply_scrambling`

```python
bits = np.asarray(bits, dtype=np.uint8)
rng = np.random.default_rng(seed)
scrambling_sequence = rng.integers(0, 2, len(bits), dtype=np.uint8)
return np.bitwise_xor(bits, scrambling_sequence)
```

Se genera una secuencia pseudoaleatoria de bits y se aplica XOR. La misma funcion se usa en recepcion para descrambling porque:

```text
a XOR b XOR b = a
```

## 8. Mapeo de bits a simbolos de modulacion

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

```python
tx_symbols = utils.map_bits_to_symbols(tx_bits, mod_type)
```

Archivo: `core/utils.py`  
Funcion: `map_bits_to_symbols`

```python
n_bits = _bits_per_symbol(mod_type)
bits = np.asarray(bits, dtype=np.uint8)

remainder = len(bits) % n_bits
if remainder:
    bits = np.pad(bits, (0, n_bits - remainder))

bit_groups = bits.reshape(-1, n_bits)
return _lte_modulate_groups(bit_groups, mod_type)
```

Segun `mod_type`:

| Modulation | Bits por simbolo |
| --- | ---: |
| QPSK | 2 |
| 16-QAM | 4 |
| 64-QAM | 6 |

Si la cantidad de bits no calza exactamente con la modulacion, se agrega padding con ceros al final.

El mapeo concreto se hace en:

Archivo: `core/utils.py`  
Funcion: `_lte_modulate_groups`

Ejemplo para QPSK:

```python
i = 1 - 2 * bits[:, 0]
q = 1 - 2 * bits[:, 1]
scale = 1 / np.sqrt(2)
return (i + 1j * q) * scale
```

El resultado es un arreglo de simbolos complejos.

## 9. Insercion de pilotos y modulacion OFDM

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

```python
ofdm_time_signal, num_blocks = ofdm_ops.modulate_ofdm_with_pilots(
    tx_symbols,
    n_fft,
    nc,
)
```

Archivo: `core/ofdm_ops.py`  
Funcion: `modulate_ofdm_with_pilots`

```python
first_pilot_mask = pilot_subcarrier_mask(nc, pilot_spacing, 0, pilot_staggered)
data_per_block = nc - int(np.sum(first_pilot_mask))
```

La mascara de pilotos se define asi:

Archivo: `core/ofdm_ops.py`  
Funcion: `pilot_subcarrier_mask`

```python
offset = _pilot_offset(block_idx, pilot_spacing, staggered)
return ((np.arange(nc) - offset) % pilot_spacing) == 0
```

Y los parametros de pilotos estan en:

Archivo: `core/config.py`

```python
PILOT_SPACING_SC = LTE_CRS_REFERENCE_SPACING_SC
PILOT_STAGGER_OFFSET_SC = PILOT_SPACING_SC // 2
PILOT_STAGGER_ENABLED = True
CHANNEL_ESTIMATION_RIDGE = 1e-2
PILOT_SEED = 36_211
```

Luego se arma la grilla activa:

```python
active_grid = np.zeros((num_blocks, nc), dtype=np.complex128)
pilots = pilot_symbol_grid(num_blocks, int(pilot_counts[0]), pilot_seed)
for block_idx in range(num_blocks):
    pilot_mask = pilot_masks[block_idx]
    active_grid[block_idx, pilot_mask] = pilots[block_idx]
    active_grid[block_idx, ~pilot_mask] = data_grid[block_idx]
```

Es decir:

- las posiciones de pilotos reciben una secuencia QPSK deterministica conocida
  por transmisor y receptor;
- las demas posiciones reciben datos de la imagen.

Usar una secuencia QPSK evita que todos los pilotos tengan la misma fase. Eso
mantiene los pilotos conocidos para estimar canal, pero evita picos artificiales
en PAPR causados por una peineta de pilotos constantes.

Finalmente se mapea la grilla activa a bins de FFT y se aplica IFFT:

Archivo: `core/ofdm_ops.py`  
Funcion: `_map_active_grid_to_time`

```python
freq_grid = np.zeros((active_grid.shape[0], n_fft), dtype=np.complex128)
freq_grid[:, active_subcarrier_indices(n_fft, nc)] = active_grid
return np.fft.ifft(freq_grid, axis=1) * np.sqrt(n_fft)
```

## 10. Ubicacion de subportadoras activas

Archivo: `core/ofdm_ops.py`  
Funcion: `active_subcarrier_indices`

```python
half = nc // 2
negative = np.arange(n_fft - half, n_fft)
positive = np.arange(1, half + 1)
return np.concatenate((negative, positive))
```

Esto coloca la mitad de subportadoras en frecuencias negativas y la mitad en frecuencias positivas, dejando DC vacia.

## 11. Prefijo ciclico

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

```python
tx_signal_cp, cp_used = ofdm_ops.add_cyclic_prefix(
    ofdm_time_signal,
    num_blocks,
    n_fft,
    cp_lengths,
)
```

Archivo: `core/ofdm_ops.py`  
Funcion: `add_cyclic_prefix`

```python
cp_lengths = _cp_lengths_for_blocks(cp_config, num_blocks, n_fft)
blocks = signal.reshape(num_blocks, n_fft)

with_cp = [
    np.concatenate((block[-cp_len:], block))
    for block, cp_len in zip(blocks, cp_lengths)
]
return np.concatenate(with_cp), cp_lengths
```

El prefijo ciclico copia el final de cada simbolo OFDM y lo pone al inicio.

Las longitudes base del CP estan en `core/config.py`:

```python
LTE_PROFILES = {
    1: {"name": "Normal", "delta_f_hz": DELTA_F_HZ, "cp_ref": (160, 144, 144, 144, 144, 144, 144)},
    2: {"name": "Extendido", "delta_f_hz": DELTA_F_HZ, "cp_ref": (512, 512, 512, 512, 512, 512)},
}
```

Luego se escalan segun el tamano FFT.

## 12. Canal

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

```python
sample_rate_hz = n_fft * df
rx_signal_cp, _ = channel.apply_rayleigh(
    tx_signal_cp,
    snr_db,
    num_taps=num_paths,
    sample_rate_hz=sample_rate_hz,
    rng=rng,
)
```

Archivo: `core/channel.py`  
Funcion: `apply_rayleigh`

```python
signal_convolved = np.convolve(signal, h, mode="full")[:len(signal)]
signal_noisy = apply_awgn(signal_convolved, snr_db, rng=rng, reference_power=tx_power)
return signal_noisy, h
```

El canal hace dos cosas:

1. Convoluciona la senal con una respuesta impulsiva multipath `h`.
2. Agrega ruido blanco gaussiano complejo segun la SNR.

En la transmision manual, `rng` usa por defecto la semilla fija
`image_tx_seed = 2024`, definida en `OFDMSimulationManager`. Asi, repetir la
misma configuracion genera la misma realizacion de canal y ruido, lo que facilita
comparar visualmente cambios de parametros. Para pruebas especificas,
`run_image_transmission` permite pasar `rng_seed` y sobrescribir esa semilla.

La respuesta `h` se genera en:

Archivo: `core/channel.py`  
Funcion: `generate_rayleigh_channel`

```python
sample_delays = np.rint(delays_s * sample_rate_hz).astype(int)
h = np.zeros(int(np.max(sample_delays)) + 1, dtype=np.complex128)
for delay, power, coeff in zip(sample_delays, power_linear, fading):
    h[int(delay)] += np.sqrt(power) * coeff
return h
```

El simulador usa por defecto el perfil `Didactico CP`, definido en
`core/channel.py`. Este perfil no es ITU: se agrego para mostrar de forma clara
el efecto del prefijo ciclico, con un camino directo y un eco a `12 us`.
Tambien quedan disponibles los perfiles ITU Pedestrian/Vehicular para pruebas
mas realistas. El slider de la interfaz selecciona un slice inicial del perfil:
con valor `N` se usan los primeros `N` caminos del perfil.

La parte importante para OFDM es que los retardos fisicos del perfil se convierten
a muestras usando:

```text
Fs = NFFT * Delta_f
delay_samples = round(delay_seconds * Fs)
```

Por ejemplo, con 10 MHz LTE se usa `NFFT = 1024` y `Delta_f = 15 kHz`,
por lo que `Fs = 15.36 MHz`. En `Didactico CP`, el eco de `12 us` cae alrededor
de `184` muestras. Si varios caminos caen en la misma muestra, sus coeficientes
complejos se suman en ese tap discreto.

La potencia del PDP se normaliza en promedio, no por realizacion instantanea.
Esto conserva la variacion natural de potencia de un canal Rayleigh. El ruido
AWGN se calcula con referencia a la potencia transmitida para que las
atenuaciones del canal afecten la SNR recibida.

Antes de transmitir, el simulador calcula si el retardo maximo cabe en el CP:

```text
margen = CP_minimo - retardo_maximo
```

Si el margen es negativo, la interfaz lo marca como una condicion con ISI
esperada. Con `Didactico CP`, el CP normal queda corto y el CP extendido si
cubre el eco en las numerologias LTE incluidas.

## 13. Recepcion: quitar prefijo ciclico

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

```python
rx_signal_no_cp = ofdm_ops.remove_cyclic_prefix(
    rx_signal_cp,
    n_fft,
    cp_used,
)
```

Archivo: `core/ofdm_ops.py`  
Funcion: `remove_cyclic_prefix`

La funcion recorre bloque por bloque, salta las muestras de CP y conserva solo la parte util de longitud `n_fft`.

## 14. FFT, estimacion de canal y ecualizacion

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

```python
rx_symbols_equalized, _ = ofdm_ops.demodulate_ofdm_with_pilots(
    rx_signal_no_cp,
    n_fft,
    nc,
    max_channel_taps=len(h_used),
)
```

Archivo: `core/ofdm_ops.py`  
Funcion: `demodulate_ofdm_with_pilots`

Primero se aplica FFT y se recupera la grilla activa:

```python
active_grid = _time_to_active_grid(rx_time_signal, n_fft, nc)
```

Luego se construye la mascara de pilotos por bloque:

```python
pilot_masks = pilot_subcarrier_masks(num_blocks, nc, pilot_spacing, pilot_staggered)
```

Se estima el canal en las posiciones piloto y se promedia en tiempo:

```python
known_indices, h_known = _average_pilot_observations(active_grid, pilot_masks, pilots, nc)
```

Cuando se conoce el soporte temporal del canal simulado, se usa una estimacion
DFT/LS regularizada:

```python
h_taps = weights @ h_known
h_active = np.fft.fft(h_time)[active_subcarrier_indices(n_fft, nc)]
```

Y se ecualiza:

```python
equalized_grid = active_grid / h_est
return np.concatenate(data_blocks), h_est
```

El receptor ya no necesita conocer directamente la respuesta impulsiva real `h` del canal. La estima desde los pilotos recibidos.

## 15. Demapeo de simbolos a bits

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

```python
rx_bits_scrambled = utils.demap_symbols_to_bits(rx_symbols_equalized, mod_type)
```

Archivo: `core/utils.py`  
Funcion: `demap_symbols_to_bits`

```python
points = np.array(list(constellation.values()), dtype=np.complex128)
bit_maps = np.array(list(constellation.keys()), dtype=np.uint8)
distances = np.abs(chunk[:, None] - points[None, :]) ** 2
nearest = np.argmin(distances, axis=1)
```

Para cada simbolo recibido se busca el punto de constelacion mas cercano. Ese punto decide los bits estimados.

## 16. Descrambling

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

Primero se recorta la longitud valida:

```python
valid_len = len(tx_bits_raw)
rx_bits_scrambled = rx_bits_scrambled[:valid_len]
```

Luego se aplica la misma funcion XOR:

```python
rx_bits = utils.apply_scrambling(rx_bits_scrambled)
```

Esto revierte el scrambling aplicado en transmision.

## 17. Calculo de BER

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

```python
bit_errors = np.sum(tx_bits_raw != rx_bits)
ber = bit_errors / valid_len
```

La BER compara bit a bit:

```text
bits originales de la imagen vs bits recuperados
```

## 18. Reconstruccion de imagen

Archivo: `controller/simulation_mgr.py`  
Funcion: `run_image_transmission`

```python
rx_img_matrix = utils.bits_to_image(rx_bits, img_size)
```

Archivo: `core/utils.py`  
Funcion: `bits_to_image`

```python
expected_len = size * size * 8
bits = np.asarray(bits, dtype=np.uint8)
if len(bits) < expected_len:
    bits = np.pad(bits, (0, expected_len - len(bits)))
bits = bits[:expected_len]
img = np.packbits(bits)
return img.reshape((size, size))
```

Esta funcion:

1. asegura que haya exactamente `250*250*8` bits;
2. agrupa bits en bytes con `np.packbits`;
3. reorganiza la matriz a `250x250`.

## 19. Visualizacion en interfaz

Archivo: `ui/main_window.py`  
Funcion: `_show_image_result`

Si el resultado fue exitoso, la interfaz convierte las matrices NumPy a imagenes:

```python
img_tx_pil = Image.fromarray(result["tx_image"]).resize((300, 300), Image.Resampling.NEAREST)
img_rx_pil = Image.fromarray(result["rx_image"]).resize((300, 300), Image.Resampling.NEAREST)
```

Luego las muestra:

```python
self.lbl_tx_img.configure(image=self.tk_img_tx, text="")
self.lbl_rx_img.configure(image=self.tk_img_rx, text="")
self.lbl_status.configure(text=result["info"], text_color="#30D760")
```

El texto de estado resume:

```text
BER | bits totales de la imagen | simbolos modulados | bloques OFDM | subportadoras activas
```

Los bits corresponden a la imagen ya redimensionada. Los simbolos dependen de
la modulacion seleccionada: QPSK usa 2 bits por simbolo, 16-QAM usa 4 y 64-QAM
usa 6, con padding al final si hiciera falta. Los bloques OFDM indican cuantas
IFFT/bloques temporales fueron necesarios para transportar esos simbolos tras
reservar las subportadoras piloto. Por eso cambian con la modulacion, con el
ancho de banda y con la cantidad de subportadoras activas.

## 20. Resumen corto de la cadena

```text
Imagen
  -> escala de grises
  -> resize 250x250
  -> bits
  -> scrambling
  -> simbolos QPSK/16-QAM/64-QAM
  -> grilla OFDM con pilotos
  -> IFFT
  -> prefijo ciclico
  -> canal multipath + AWGN
  -> quitar CP
  -> FFT
  -> estimacion de canal por pilotos
  -> ecualizacion
  -> demapeo a bits
  -> descrambling
  -> BER
  -> reconstruccion de imagen
```

## 21. Donde se calcula cada analisis

Transmision de una imagen:

```text
ui/main_window.py::action_run_image
ui/main_window.py::_start_worker
ui/main_window.py::_show_image_result
controller/simulation_mgr.py::run_image_transmission
```

Curva BER:

```text
ui/main_window.py::action_plot_ber
controller/simulation_mgr.py::calculate_ber_curve
controller/simulation_mgr.py::_calculate_ber_series
```

La curva BER usa la imagen cargada como carga util y se calcula para QPSK,
16-QAM y 64-QAM. En la interfaz se reportan las corridas Monte Carlo usadas por
punto, los bloques OFDM por corrida de cada modulacion, el ancho de banda, las
subportadoras activas, el prefijo ciclico, el perfil de canal activo y el
numero de caminos multipath seleccionados.

Curva PAPR:

```text
ui/main_window.py::action_plot_papr
controller/simulation_mgr.py::calculate_papr_distribution
controller/simulation_mgr.py::_calculate_papr_values
```

La curva PAPR no usa Monte Carlo. Evalua los bloques OFDM que salen de la
imagen cargada para las tres modulaciones. Como el PAPR se mide antes del
prefijo ciclico y antes del canal, el resumen solo reporta ancho de banda,
subportadoras activas, bloques evaluados, sobremuestreo `L=4` y
`CP/canal: no aplican`.

Funciones OFDM principales:

```text
core/ofdm_ops.py::modulate_ofdm_with_pilots
core/ofdm_ops.py::add_cyclic_prefix
core/ofdm_ops.py::remove_cyclic_prefix
core/ofdm_ops.py::demodulate_ofdm_with_pilots
```

Funciones de imagen/modulacion:

```text
core/utils.py::image_to_bits
core/utils.py::apply_scrambling
core/utils.py::map_bits_to_symbols
core/utils.py::demap_symbols_to_bits
core/utils.py::bits_to_image
```
