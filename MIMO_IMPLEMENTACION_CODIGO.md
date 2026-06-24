# Implementacion MIMO en el codigo

Este documento explica como la teoria MIMO queda representada en el codigo del
simulador. Esta actualizado para la version simplificada: todas las
subportadoras activas transportan datos, el canal generado se usa directamente
en recepcion y las curvas BER usan bits aleatorios reproducibles.

## 1. Arquitectura general

La cadena esta repartida en cuatro zonas:

| Archivo | Responsabilidad |
| --- | --- |
| `core/config.py` | Parametros LTE, modulaciones, modos MIMO y detectores. |
| `core/ofdm_ops.py` | OFDM, precoding, FFT/IFFT, ecualizacion y deteccion MIMO. |
| `core/channel.py` | Canales Rayleigh SISO/MIMO y AWGN. |
| `controller/simulation_mgr.py` | Orquesta imagen, BER, MIMO visual, canal y metricas. |
| `ui/main_window.py` | Interfaz grafica, controles y graficas. |
| `tests/test_core.py` | Pruebas de core, canal, MIMO, manager y UI. |

La division importante es:

```text
Core       -> operaciones matematicas puras
Controller -> arma experimentos completos
UI         -> muestra resultados y lanza workers
```

## 2. Configuracion MIMO

Los modos MIMO se definen en `core/config.py`:

```python
MIMO_MODES = {
    1: {"name": "SISO 1x1", "n_tx": 1, "n_rx": 1, "layers": 1, "precoder": "identity"},
    2: {"name": "SM 2x2", "n_tx": 2, "n_rx": 2, "layers": 2, "precoder": "identity"},
    3: {"name": "SM 4x4", "n_tx": 4, "n_rx": 4, "layers": 4, "precoder": "identity"},
    4: {"name": "SM 4x2", "n_tx": 4, "n_rx": 2, "layers": 2, "precoder": "tx_repeat"},
    5: {"name": "SM 4x4 R2", "n_tx": 4, "n_rx": 4, "layers": 2, "precoder": "tx_repeat"},
}
```

Campos clave:

- `n_tx`: numero de antenas transmisoras fisicas.
- `n_rx`: numero de antenas receptoras fisicas.
- `layers`: numero de flujos espaciales simultaneos.
- `precoder`: matriz usada para mapear capas a antenas TX.

Los detectores tambien se configuran ahi:

```python
MIMO_DETECTORS = {
    1: "ZF",
    2: "IRC/MMSE",
    3: "MMSE-SIC",
}
```

`IRC/MMSE` es la etiqueta de interfaz para el detector MMSE regularizado. No es
un receptor LTE-IRC completo con matriz general de covarianza de interferencia.

## 3. Subportadoras activas

La funcion:

```python
active_subcarrier_indices(n_fft, nc)
```

esta en `core/ofdm_ops.py` y devuelve los indices FFT de las subportadoras
activas alrededor de DC. El bin DC queda vacio, como corresponde a la idea base
de OFDM LTE.

La version actual usa todas esas subportadoras activas para datos. Por eso:

```python
_data_subcarriers_per_layer(nc, mimo_mode) -> nc
```

en `controller/simulation_mgr.py`.

## 4. Respuesta de canal conocida

El receptor usa CSI directa. La funcion:

```python
channel_frequency_response(h, n_fft, nc)
```

toma la respuesta impulsiva del canal y calcula `H[k]` en las subportadoras
activas.

Para SISO:

```text
h -> H[k]
forma: (nc,)
```

Para MIMO:

```text
h -> H[k]
h tiene forma:       (n_rx, n_tx, taps)
H[k] tiene forma:    (nc, n_rx, n_tx)
```

Esta funcion reemplaza toda la complejidad anterior de insertar senales de
referencia y reconstruir el canal. El canal se genera en `core/channel.py` y se
entrega directamente al receptor.

## 5. Precoding

El precoder se construye con:

```python
mimo_precoder_matrix(n_tx, n_layers=None, precoder="identity")
```

Casos implementados:

### Identidad

Usado por `SISO 1x1`, `SM 2x2` y `SM 4x4`.

```text
n_tx == layers
W = I
```

Cada capa va a una antena TX distinta.

### tx_repeat

Usado por `SM 4x2`.

```text
n_tx = 4
layers = 2
```

La matriz resultante es equivalente a:

```text
W = 1/sqrt(2) * [[1, 0],
                 [0, 1],
                 [1, 0],
                 [0, 1]]
```

Esto reparte dos capas sobre cuatro antenas TX. El codigo valida que:

```text
W^H W = I
```

asi las columnas del precoder son ortonormales.

## 6. Modulacion OFDM SISO

Para SISO se usa:

```python
modulate_ofdm(symbols, n_fft, nc)
```

Flujo interno:

1. Calcula cuantos bloques OFDM hacen falta.
2. Agrega padding de simbolos complejos si hace falta.
3. Llena una matriz `(num_blocks, nc)`.
4. Inserta esa matriz en los bins activos de la FFT.
5. Aplica IFFT normalizada.
6. Devuelve la senal temporal y el numero de bloques.

La funcion no reserva subportadoras especiales; `nc` subportadoras activas
transportan datos.

## 7. Modulacion OFDM MIMO

Para MIMO se usa:

```python
modulate_mimo_ofdm(
    symbols,
    n_fft,
    nc,
    n_tx=2,
    n_layers=None,
    precoder="identity",
)
```

La entrada es una sola secuencia de simbolos QAM. El simulador no usa varias
imagenes ni varios usuarios. La secuencia se reparte round-robin en capas:

```text
simbolo 0 -> capa 0
simbolo 1 -> capa 1
simbolo 2 -> capa 0
simbolo 3 -> capa 1
...
```

Para `4x4` hay cuatro capas:

```text
simbolo 0 -> capa 0
simbolo 1 -> capa 1
simbolo 2 -> capa 2
simbolo 3 -> capa 3
simbolo 4 -> capa 0
...
```

La funcion auxiliar:

```python
_split_symbols_into_layers(symbols, n_layers, num_blocks, data_per_layer)
```

crea la grilla por capas. Luego, para cada bloque OFDM:

```python
active_grids[:, block_idx, :] = precoder_matrix @ layer_grid[:, block_idx, :]
```

Eso convierte capas espaciales en senales por antena TX fisica.

Finalmente cada antena TX pasa por el mismo proceso OFDM: bins activos, IFFT y
senal temporal.

## 8. Prefijo ciclico

El CP se aplica con:

```python
add_cyclic_prefix(signal, num_blocks, n_fft, cp_config)
```

y se retira con:

```python
remove_cyclic_prefix(rx_signal, n_fft, cp_config)
```

El manager oculta CP en la interfaz y usa el valor predeterminado para no
distraer de la practica MIMO. La logica sigue existiendo porque el canal
multipath y OFDM dependen de ella.

## 9. Canal SISO y MIMO

En `core/channel.py` estan:

```python
generate_rayleigh_channel(...)
apply_rayleigh(...)
generate_mimo_rayleigh_channel(...)
apply_mimo_rayleigh(...)
```

Para MIMO:

```python
generate_mimo_rayleigh_channel(n_tx, n_rx, num_taps, ...)
```

devuelve una matriz:

```text
(n_rx, n_tx, taps)
```

Cada enlace TX-RX tiene una realizacion Rayleigh independiente.

```python
apply_mimo_rayleigh(tx_signals, snr_db, ...)
```

recibe:

```text
tx_signals: (n_tx, muestras)
```

y devuelve:

```text
rx_signals: (n_rx, muestras)
h:          (n_rx, n_tx, taps)
```

La senal recibida se calcula sumando convoluciones:

```text
rx[rx_idx] += conv(tx[tx_idx], h[rx_idx, tx_idx])
```

Luego se agrega AWGN por antena RX usando como referencia la potencia total
transmitida.

## 10. Escalamiento de potencia

En `controller/simulation_mgr.py`, `_prepare_tx_signal` aplica:

```python
tx_scale = 1 / np.sqrt(mode_cfg["layers"])
```

cuando hay mas de una capa.

La idea es que `SM 4x4` no gane potencia total por tener cuatro capas. Se
compara contra `2x2` y `4x2` con potencia total comparable.

Ese mismo factor se pasa al receptor:

```python
channel_scale=tx_plan["tx_scale"]
```

para que `H[k]` efectivo incluya la escala que realmente se transmitio.

## 11. Demodulacion SISO con CSI directa

La ruta SISO usa:

```python
demodulate_ofdm_with_channel(
    rx_time_signal,
    n_fft,
    nc,
    h,
    noise_to_signal=0.0,
    channel_scale=1.0,
)
```

Pasos:

1. Convierte la senal temporal recibida a grilla activa con FFT.
2. Calcula `H[k]` desde `h`.
3. Aplica una ecualizacion tipo MMSE escalar:

```text
x_hat[k] = y[k] H*[k] / (|H[k]|^2 + sigma2)
```

Con `sigma2 = 0` se aproxima a inversion ZF escalar.

## 12. Demodulacion MIMO con CSI directa

La ruta MIMO usa:

```python
demodulate_mimo_ofdm_with_channel(
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
)
```

Pasos:

1. Aplica FFT a cada antena RX.
2. Calcula el canal fisico `H_phys[k]` desde `h`.
3. Construye el precoder `W`.
4. Calcula el canal efectivo:

```text
H_eff[k] = H_phys[k] @ W
```

5. Aplica la escala de potencia:

```text
H_eff[k] = H_eff[k] * tx_scale
```

6. Detecta capas por subportadora.
7. Intercala nuevamente las capas con `_interleave_layer_symbols`.

Para `4x2`, este punto es clave:

```text
H_phys[k]: 2 x 4
W:         4 x 2
H_eff[k]:  2 x 2
```

El detector trabaja sobre `H_eff`, no sobre la matriz fisica completa.

## 13. Detectores MIMO

La funcion publica es:

```python
detect_mimo_symbols(y, h_matrix, detector="MMSE", ...)
```

Acepta un vector o batch de vectores recibidos y una matriz de canal efectiva.

### ZF

```python
weights = np.linalg.pinv(h_matrix)
detected = weights @ y
```

Sirve como referencia teorica simple, pero puede amplificar ruido.

### IRC/MMSE

La ruta:

```python
_detect_linear_mmse(y, h_matrix, noise_to_signal, threshold)
```

resuelve:

```text
(H^H H + sigma2 I) s_hat = H^H y
```

El termino `sigma2 I` estabiliza la inversion cuando hay ruido o cuando el canal
esta mal condicionado.

### MMSE-SIC

La ruta:

```python
_detect_mmse_sic(y, h_matrix, mod_type, noise_to_signal, threshold)
```

trabaja por etapas:

1. Ordena las capas por potencia de columna del canal.
2. Estima las capas activas con MMSE.
3. Escoge la capa del paso actual.
4. Cuantiza al simbolo QAM mas cercano con `quantize_symbols_to_constellation`.
5. Resta esa contribucion del residual.
6. Continua con las demas capas.

Esto implementa Successive Interference Cancellation de forma didactica.

## 14. Manager: preparacion de transmision

El metodo:

```python
_prepare_tx_signal(...)
```

hace el bloque transmisor comun:

1. Obtiene `n_fft`, `nc`, CP y `df`.
2. Lee el modo MIMO.
3. Aplica scrambling.
4. Mapea bits a simbolos QAM.
5. Llama a `modulate_ofdm` o `modulate_mimo_ofdm`.
6. Agrega CP.
7. Escala por `1/sqrt(layers)` si corresponde.
8. Devuelve un `tx_plan` con todos los metadatos.

El `tx_plan` incluye:

- `tx_cp`: senal temporal con CP.
- `n_fft`, `nc`, `sample_rate_hz`.
- `num_blocks`, `num_symbols`.
- `num_layers`, `n_tx`, `n_rx`.
- `precoder_matrix`.
- `tx_scale`.
- `data_subcarriers_per_layer`.
- `num_layers`.

## 15. Manager: recepcion

El metodo:

```python
_receive_bits(...)
```

hace el receptor:

1. Retira CP.
2. Demodula OFDM con el canal conocido `h`.
3. Detecta SISO o MIMO.
4. Demapea simbolos a bits.
5. Recorta padding.
6. Revierte scrambling.

La firma recibe `h` directamente. Ese es el cambio central de simplificacion:
el receptor ya no necesita reconstruir el canal desde observaciones auxiliares.

## 16. Transmision de imagen

La funcion publica:

```python
run_image_transmission(...)
```

ejecuta la cadena completa con una imagen:

```text
imagen -> bits -> QAM -> OFDM -> canal -> receptor -> bits -> imagen
```

Devuelve:

- imagen transmitida y recibida;
- BER;
- SNR;
- modo MIMO;
- detector;
- antenas;
- capas;
- bloques OFDM;
- numero de capas;
- condicion media/mediana de `H[k]`;
- capacidad ideal aproximada.

Esta ruta se conserva como API interna y se reutiliza para construir la grilla
visual de `PRUEBA MULTIANTENA`.

## 17. Curvas BER con bits aleatorios

La funcion:

```python
_random_ber_bits(seed_offset=0)
```

genera una carga util reproducible:

```python
rng = np.random.default_rng(self.mc_seed + 50_000 + seed_offset)
```

La funcion:

```python
calculate_ber_curve(...)
```

ignora intencionalmente la imagen y compara siempre:

```text
QPSK
16-QAM
64-QAM
```

bajo el modo MIMO activo.

Esto hace que las curvas midan BER estadistica del enlace, no caracteristicas
particulares de `cameraman` u otra imagen.

## 18. Comparacion multiantena

La funcion:

```python
_mimo_comparison_scenarios(rank_mode="max")
```

define seis escenarios:

```text
2x2 R2 IRC/MMSE
4x2 R2 IRC/MMSE
4x4 R2 o R4 IRC/MMSE
2x2 R2 SIC
4x2 R2 SIC
4x4 R2 o R4 SIC
```

La comparacion se divide en dos partes:

### Visual

```python
calculate_mimo_visual_comparison(...)
```

transmite la imagen una vez por escenario. Sirve para mostrar reconstrucciones
visuales en una grilla 2x3.

### BER

```python
calculate_mimo_comparison(...)
```

usa bits aleatorios reproducibles y genera curvas BER para los mismos seis
escenarios, con la modulacion activa y el rank seleccionados en la UI.

### Tarea combinada

```python
calculate_mimo_analysis(...)
```

devuelve:

```python
{
    "visual": ...,
    "ber": ...,
    "summary": ...,
}
```

La UI lo usa para llenar la pestana de prueba multiantena y la de comparacion
MIMO.

## 19. Metricas de canal

El metodo:

```python
_channel_metrics(h, tx_plan, snr_db)
```

calcula:

- condicion media de `H[k]`;
- condicion mediana de `H[k]`;
- capacidad ideal aproximada en bps/Hz.

Para MIMO, si hay precoder, primero calcula:

```text
H_eff[k] = H_phys[k] @ W
```

y luego obtiene valores singulares. La condicion:

```text
cond(H) = sigma_max / sigma_min
```

indica que tan dificil es separar capas. Una condicion alta suele anticipar
peor desempeno, especialmente con ZF.

## 20. UI

En `ui/main_window.py`:

- La barra lateral conserva solo modulacion, SNR, seleccion de imagen y el boton
  `PRUEBA MULTIANTENA`.
- La pestana `Imagen Original` muestra la imagen seleccionada como referencia.
- La pestana `Prueba Multiantena` muestra las seis reconstrucciones:
  `2x2 IRC/MMSE`, `4x2 IRC/MMSE`, `4x4 IRC/MMSE`, `2x2 SIC`, `4x2 SIC` y
  `4x4 SIC`.
- El selector `Rank comparacion` permite elegir `Rank 2` o `Rank maximo`.
- El boton `CURVAS BER` genera la pestana `BER MIMO` con las seis curvas BER.
- En `Rank 2`, el escenario 4x4 usa el modo interno `SM 4x4 R2`: 4 TX, 4 RX,
  2 capas y precoder `tx_repeat`.
- En `Rank maximo`, el escenario 4x4 usa 4 capas.

La interfaz oculta ancho de banda, CP, multipath, selector MIMO y selector de
detector para reducir ruido visual. El manager conserva esos valores y
escenarios como configuracion interna.

## 21. Pruebas relevantes

`tests/test_core.py` cubre:

- Parametros LTE y CP.
- Mapeo/demapeo QPSK, 16-QAM y 64-QAM.
- Roundtrip OFDM SISO con canal directo conocido.
- Canal Rayleigh MIMO 2x2 y 4x4.
- Precoder 4x2 con `W^H W = I`.
- Detectores ZF, IRC/MMSE y MMSE-SIC.
- Roundtrip MIMO 2x2, 4x2 y 4x4 con canal conocido.
- `run_image_transmission` en SISO, 2x2, 4x2 y 4x4.
- Curvas BER con bits aleatorios.
- Comparacion multiantena con las seis etiquetas esperadas.
- Creacion basica de la ventana UI.

Comandos de validacion:

```bash
venv/bin/python -m compileall main.py controller core ui tests
venv/bin/python -m unittest discover -v
```

## 22. Lectura rapida del flujo completo

```text
config.py
  define modos y detectores

simulation_mgr.py
  _prepare_tx_signal
    bits -> scrambling -> QAM -> OFDM/MIMO -> CP -> escala

channel.py
  apply_rayleigh / apply_mimo_rayleigh
    senal TX -> canal multipath + AWGN -> senal RX + h

simulation_mgr.py
  _receive_bits
    RX -> quitar CP -> FFT -> usar h directo -> detectar -> bits

ofdm_ops.py
  demodulate_mimo_ofdm_with_channel
    h -> H[k] -> H_eff[k] -> ZF/MMSE/SIC

simulation_mgr.py
  calcula BER, imagen reconstruida y metricas
```

## 23. Como defender la simplificacion

La simplificacion no cambia el objetivo MIMO. Quita una parte que pertenece mas
a estimacion de canal OFDM/LTE y deja fijo el supuesto:

```text
el receptor conoce el canal generado por la simulacion
```

Con eso la practica se concentra en:

- multiplexacion espacial;
- rank y capas;
- precoding fijo 4x2;
- deteccion ZF, IRC/MMSE y SIC;
- comparacion visual;
- curvas BER por modulacion y arreglo multiantena.

Para una presentacion academica, la forma honesta de decirlo es:

> En esta version usamos CSI directa para aislar el problema MIMO. No estamos
> evaluando estimacion de canal, sino la recuperacion de capas espaciales bajo
> diferentes arreglos de antenas y detectores.
