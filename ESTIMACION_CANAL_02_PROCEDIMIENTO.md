# Estimacion de canal 02 - Procedimiento del programa

Este archivo explica el procedimiento con mas detalle que el resumen anterior,
siguiendo el orden real del codigo.

## 1. Parametros de pilotos

Los parametros estan en `core/config.py`:

```python
LTE_CRS_REFERENCE_SPACING_SC = 6
PILOT_SPACING_SC = LTE_CRS_REFERENCE_SPACING_SC
PILOT_STAGGER_OFFSET_SC = PILOT_SPACING_SC // 2
PILOT_STAGGER_ENABLED = True
CHANNEL_ESTIMATION_RIDGE = 1e-2
PILOT_SEED = 36_211
```

El valor base `PILOT_SPACING_SC = 6` significa que, dentro de un bloque OFDM,
hay una piloto cada 6 subportadoras activas. Como el patron esta escalonado, el
siguiente bloque se desplaza 3 subportadoras.

Ejemplo conceptual:

```text
Bloque 0: P . . . . . P . . . . . P ...
Bloque 1: . . . P . . . . . P . . . ...
```

La ventaja es que se conserva un overhead de pilotos parecido a LTE, pero al
observar dos bloques consecutivos se obtiene informacion intermedia.

## 2. Construccion de la mascara de pilotos

La mascara se construye en `core/ofdm_ops.py`:

```python
def pilot_subcarrier_mask(nc, pilot_spacing, block_idx, staggered):
    offset = _pilot_offset(block_idx, pilot_spacing, staggered)
    return ((np.arange(nc) - offset) % pilot_spacing) == 0
```

Aqui:

- `nc` es el numero de subportadoras activas.
- `pilot_spacing` es la separacion base.
- `block_idx` indica el bloque OFDM.
- `offset` permite alternar el patron entre bloques.

Para varios bloques se usa:

```python
pilot_subcarrier_masks(num_blocks, nc, pilot_spacing, staggered)
```

Esta funcion devuelve una matriz booleana de tamano:

```text
num_blocks x nc
```

Cada fila indica donde van los pilotos de ese bloque.

## 3. Insercion de pilotos en transmision

La funcion que arma el OFDM con pilotos es:

```python
modulate_ofdm_with_pilots(...)
```

Primero se calcula cuantas subportadoras quedan para datos:

```python
first_pilot_mask = pilot_subcarrier_mask(nc, pilot_spacing, 0, pilot_staggered)
data_per_block = nc - int(np.sum(first_pilot_mask))
```

Despues se generan las mascaras de todos los bloques:

```python
pilot_masks = pilot_subcarrier_masks(num_blocks, nc, pilot_spacing, pilot_staggered)
```

Luego se generan pilotos QPSK deterministicos:

```python
pilots = pilot_symbol_grid(num_blocks, int(pilot_counts[0]), pilot_seed)
```

Finalmente, por cada bloque:

```python
active_grid[block_idx, pilot_mask] = pilots[block_idx]
active_grid[block_idx, ~pilot_mask] = data_grid[block_idx]
```

Esto produce una grilla activa que contiene datos y pilotos. Luego se aplica:

```python
time_grid = _map_active_grid_to_time(active_grid, n_fft, nc)
```

Internamente esa funcion coloca las subportadoras activas en la FFT y aplica
IFFT.

## 4. Paso por el canal

En `controller/simulation_mgr.py`, la senal OFDM con CP pasa por el canal:

```python
rx_signal_cp, h_used = channel.apply_rayleigh(...)
```

La variable `h_used` contiene la respuesta impulsiva usada por el simulador.
Luego se retira el CP:

```python
rx_signal_no_cp = ofdm_ops.remove_cyclic_prefix(rx_signal_cp, n_fft, cp_used)
```

Y se llama al demodulador con pilotos:

```python
rx_symbols_equalized, _ = ofdm_ops.demodulate_ofdm_with_pilots(
    rx_signal_no_cp,
    n_fft,
    nc,
    max_channel_taps=len(h_used),
    noise_to_signal=10 ** (-snr_db / 10),
)
```

El argumento `max_channel_taps` permite que el estimador sepa cuantos taps
temporales debe considerar para reconstruir el canal.

## 5. FFT en recepcion

Dentro de `demodulate_ofdm_with_pilots`, primero se convierte la senal recibida
al dominio de frecuencia:

```python
active_grid = _time_to_active_grid(rx_time_signal, n_fft, nc)
```

`active_grid` contiene la grilla recibida en frecuencia:

```text
Y[b, k]
```

donde:

- `b` es el bloque OFDM.
- `k` es la subportadora activa.

## 6. Estimacion LS en pilotos

El modelo simplificado en una subportadora piloto es:

```text
Y_p = H_p X_p + W_p
```

Como `X_p` es conocido, una estimacion directa es:

```text
H_p = Y_p / X_p
```

En el codigo:

```python
h_ls = active_grid[block_idx, pilot_mask] / pilots[block_idx]
```

Esto se hace para todos los bloques y todas las posiciones piloto.

## 7. Promedio temporal de pilotos

El programa usa:

```python
_average_pilot_observations(...)
```

Esta funcion acumula estimaciones LS en las posiciones conocidas:

```python
sum_h[pilot_indices] += h_ls
count_h[pilot_indices] += 1
```

Luego calcula:

```python
h_known = sum_h[known_indices] / count_h[known_indices]
```

Esto reduce ruido porque el canal del simulador se mantiene constante durante
la transmision. Si el canal no cambia, promediar varias mediciones del mismo
canal mejora la estimacion.

## 8. Estimacion en dominio temporal

Cuando `max_channel_taps` esta disponible, el programa usa:

```python
_estimate_channel_from_time_domain_ls(...)
```

La idea es esta:

```text
H_pilotos = A h + ruido
```

donde:

- `H_pilotos` son las estimaciones de canal en pilotos.
- `A` es una matriz de Fourier parcial.
- `h` son los taps del canal en tiempo.

El codigo construye:

```python
basis = np.exp(-2j * np.pi * pilot_bins[:, None] * taps[None, :] / n_fft)
```

Esa matriz `basis` es la matriz `A`.

## 9. LS regularizado

Para estimar los taps se usa una solucion regularizada:

```python
gram = basis.conj().T @ basis
weights = np.linalg.solve(gram + ridge * np.eye(tap_count), basis.conj().T)
h_taps = weights @ h_known
```

Matematicamente:

```text
h_est = (A^H A + lambda I)^(-1) A^H H_pilotos
```

Ese `lambda` es:

```python
CHANNEL_ESTIMATION_RIDGE = 1e-2
```

La regularizacion evita que el estimador amplifique demasiado el ruido.

## 10. Reconstruccion de H[k]

Una vez estimados los taps temporales:

```python
h_time = np.zeros(n_fft, dtype=np.complex128)
h_time[:tap_count] = h_taps
h_active = np.fft.fft(h_time)[active_subcarrier_indices(n_fft, nc)]
```

Es decir:

1. Se forma un vector temporal `h_time`.
2. Se ponen los taps estimados al inicio.
3. Se aplica FFT.
4. Se extraen las subportadoras activas.

Asi se obtiene una estimacion de canal para todas las subportadoras activas.

## 11. Ecualizacion MMSE escalar

El controlador pasa al demodulador una razon ruido/senal aproximada:

```python
noise_to_signal = 10 ** (-snr_db / 10)
```

Con eso el receptor ecualiza:

```text
X_est[k] = H_est*[k] Y[k] / (|H_est[k]|^2 + noise_to_signal)
```

En el codigo:

```python
denom = np.abs(h_est) ** 2 + noise_to_signal
equalized_grid = active_grid * np.conj(h_est) / denom
```

Si `noise_to_signal` fuera cero, esta formula se reduce a Zero-Forcing.

## 12. Relacion con MMSE

El programa usa MMSE en dos lugares:

Primero, la estimacion de canal usa regularizacion:

```text
(A^H A + lambda I)^(-1) A^H
```

Esa estructura es compatible con una lectura LMMSE simplificada cuando `lambda`
representa una relacion entre ruido y potencia esperada del canal.

Segundo, la ecualizacion final usa:

```text
H_est*[k] / (|H_est[k]|^2 + noise_to_signal)
```

Por eso conviene decir:

```text
El programa usa estimacion LS regularizada en dominio temporal y ecualizacion
MMSE escalar por subportadora.
```
