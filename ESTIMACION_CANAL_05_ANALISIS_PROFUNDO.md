# Estimacion de canal 05 - Analisis profundo

Este archivo une la implementacion con el modelo matematico completo y aclara
con precision que hace el simulador, que aproximaciones toma y como se podria
extender hacia un MMSE mas formal.

## 1. Cadena discreta del simulador

La cadena relevante es:

```text
bits -> simbolos QAM -> grilla OFDM con pilotos -> IFFT -> CP
     -> canal multipath + AWGN
     -> quitar CP -> FFT -> estimacion de canal -> ecualizacion -> bits
```

En codigo:

- Transmision OFDM con pilotos: `core/ofdm_ops.py`, `modulate_ofdm_with_pilots`.
- Canal: `core/channel.py`, `apply_rayleigh`.
- Recepcion con pilotos: `core/ofdm_ops.py`, `demodulate_ofdm_with_pilots`.
- Coordinacion: `controller/simulation_mgr.py`.

## 2. Subportadoras activas

El programa no usa todos los bins de la FFT para datos. Usa `nc` subportadoras
activas alrededor de DC y deja DC vacia.

La funcion:

```python
active_subcarrier_indices(n_fft, nc)
```

devuelve indices FFT ordenados como:

```text
frecuencias negativas, luego frecuencias positivas
```

La respuesta estimada `H_est` siempre se calcula sobre esas mismas
subportadoras activas. Eso es importante: el canal no se estima en todo el
ancho FFT, sino en las subportadoras que transportan datos o pilotos.

## 3. Modelo con CP suficiente

Si el canal discreto tiene longitud efectiva `L` y el prefijo ciclico tiene
longitud `Ncp`, entonces OFDM se comporta idealmente si:

```text
Ncp >= L - 1
```

En ese caso la convolucion lineal canal-senal se vuelve una convolucion circular
dentro del bloque util, y la FFT diagonaliza el canal:

```text
Y_b[k] = H[k] X_b[k] + W_b[k]
```

Si el CP no alcanza:

```text
Ncp < L - 1
```

aparece interferencia intersimbolica e interportadora. En ese escenario, ningun
estimador de canal por subportadora puede corregir todo perfectamente, porque
el modelo diagonal deja de ser exacto.

## 4. Pilotos escalonados

El patron de pilotos se define por:

```text
P_b = { k : (k - o_b) mod S = 0 }
```

donde:

```text
S = 6
o_b = 0 si b es par
o_b = 3 si b es impar
```

En codigo:

```python
offset = _pilot_offset(block_idx, pilot_spacing, staggered)
mask = ((np.arange(nc) - offset) % pilot_spacing) == 0
```

Esto conserva el overhead de una piloto cada 6 subportadoras por bloque, pero
al combinar bloques pares e impares se obtiene una malla efectiva con separacion
3 en frecuencia.

Esta decision es razonable porque el simulador no modela Doppler rapido. Si el
canal fuera variante en el tiempo, promediar bloques muy separados podria
producir sesgo.

## 5. Observaciones LS en pilotos

Para cada bloque y subportadora piloto:

```text
Y_b[k_p] = H[k_p] P_b[k_p] + W_b[k_p]
```

El estimador LS escalar es:

```text
H_LS,b[k_p] = P_b^*[k_p] Y_b[k_p] / |P_b[k_p]|^2
```

Como los pilotos QPSK del codigo tienen modulo uno:

```text
|P_b[k_p]|^2 = 1
```

y queda:

```text
H_LS,b[k_p] = Y_b[k_p] / P_b[k_p]
```

El codigo usa exactamente:

```python
h_ls = active_grid[block_idx, pilot_mask] / pilots[block_idx]
```

## 6. Promedio temporal y varianza

Si para una subportadora `k` hay `N_k` observaciones LS independientes:

```text
H_i[k] = H[k] + e_i[k]
```

con:

```text
E[e_i[k]] = 0
Var(e_i[k]) = sigma_e^2
```

el promedio:

```text
H_prom[k] = (1/N_k) sum_i H_i[k]
```

tiene:

```text
E[H_prom[k]] = H[k]
Var(H_prom[k]) = sigma_e^2 / N_k
```

Por eso el promedio en `_average_pilot_observations` mejora la estabilidad de
la estimacion cuando el canal es estatico.

## 7. Reconstruccion temporal: matriz parcial de Fourier

La relacion entre taps temporales y respuesta en frecuencia es:

```text
H[k] = sum_{l=0}^{L-1} h[l] exp(-j 2 pi k l / N)
```

Para pilotos:

```text
y = A h + n
```

con:

```text
A[m, l] = exp(-j 2 pi k_m l / N)
```

En el codigo:

```python
pilot_bins = active_bins[known_indices]
taps = np.arange(tap_count)
basis = np.exp(-2j * np.pi * pilot_bins[:, None] * taps[None, :] / n_fft)
```

La variable `tap_count` se calcula como:

```python
tap_count = min(max(1, int(max_channel_taps)), n_fft, len(known_indices))
```

Esto evita estimar mas taps que ecuaciones disponibles.

## 8. Regularizacion como filtro estadistico

El codigo no usa:

```text
h = pinv(A) y
```

salvo que `ridge` fuera cero. En la practica usa:

```text
W = (A^H A + lambda I)^(-1) A^H
h_est = W y
```

En codigo:

```python
gram = basis.conj().T @ basis
weights = np.linalg.solve(gram + ridge * np.eye(tap_count), basis.conj().T)
h_taps = weights @ h_known
```

Esto es ridge/Tikhonov.

Desde optimizacion:

```text
h_est = arg min_h ||y - A h||^2 + lambda ||h||^2
```

Desde estadistica bayesiana:

```text
h ~ CN(0, sigma_h^2 I)
n ~ CN(0, sigma_n^2 I)
lambda = sigma_n^2 / sigma_h^2
```

entonces el estimador tiene forma LMMSE/MAP simplificada.

## 9. Diferencia con LMMSE completo

Un LMMSE mas realista usaria:

```text
h_LMMSE = R_hh A^H (A R_hh A^H + R_nn)^(-1) y
```

donde:

- `R_hh` describe correlacion entre taps del canal.
- `R_nn` describe el ruido de las observaciones.

El simulador no calcula esas matrices. Usa:

```text
R_hh = sigma_h^2 I
R_nn = sigma_n^2 I
```

de forma implicita, y reemplaza la relacion `sigma_n^2/sigma_h^2` por un valor
fijo:

```python
CHANNEL_ESTIMATION_RIDGE = 1e-2
```

Por eso es correcto describirlo como:

```text
estimacion DFT/LS regularizada, interpretable como LMMSE simplificado
```

No conviene llamarlo "MMSE completo".

## 10. Reconstruccion FFT

Luego:

```python
h_time = np.zeros(n_fft, dtype=np.complex128)
h_time[:tap_count] = h_taps
h_active = np.fft.fft(h_time)[active_subcarrier_indices(n_fft, nc)]
```

Esto produce:

```text
H_est = F_active h_est
```

donde `F_active` representa las filas de la DFT correspondientes a las
subportadoras activas.

La estimacion resultante se copia a todos los bloques:

```python
return np.tile(h_active, (active_grid.shape[0], 1))
```

Esto equivale a asumir canal invariante durante la transmision.

## 11. Proteccion numerica

Antes de ecualizar:

```python
denom = np.abs(h_est) ** 2 + noise_to_signal
denom[denom < threshold] = threshold
```

Esto evita divisiones por cero o casi cero cuando el canal estimado es muy
pequeno.

## 12. Ecualizador implementado: MMSE escalar

La ecualizacion final es:

```python
denom = np.abs(h_est) ** 2 + noise_to_signal
equalized_grid = active_grid * np.conj(h_est) / denom
```

Matematicamente:

```text
X_hat_MMSE[k] = H_est^*[k] Y[k] / (|H_est[k]|^2 + sigma_w^2/sigma_x^2)
```

En el codigo, `noise_to_signal` representa la razon:

```text
sigma_w^2/sigma_x^2
```

Si el ruido tiende a cero, el MMSE escalar se aproxima al caso Zero-Forcing:

```text
H_est^*[k] / |H_est[k]|^2 = 1/H_est[k]
```

## 13. Que MMSE no se implementa

Lo que no se implementa es un LMMSE completo con matrices de covarianza reales
del canal y del ruido. El estimador de canal usa una regularizacion escalar
`lambda`, no una matriz estadistica `R_hh`.

## 14. Por que la mejora actual funciona

Antes, si la estimacion dependia demasiado de interpolar pocos pilotos, un eco
largo podia producir un rizado de canal que no se reconstruia bien. Eso tapaba
el efecto del CP: la BER quedaba dominada por mala estimacion.

Ahora:

1. Los pilotos se escalonan.
2. Se promedian observaciones LS.
3. Se estima el canal como taps temporales.
4. Se reconstruye la respuesta completa con FFT.

Esto respeta mejor la estructura fisica del canal multipath.

## 15. Lectura conceptual final

La cadena matematica del programa puede resumirse asi:

```text
Y_p = diag(P) H_p + W_p
H_LS,p = Y_p / P
y = H_LS,p
y = A h + n
h_reg = (A^H A + lambda I)^(-1) A^H y
H_est = FFT(h_reg)
X_hat = H_est^* Y / (|H_est|^2 + noise_to_signal)
```

Y la clasificacion correcta es:

```text
Estimador de pilotos: LS
Estimador de canal completo: DFT/LS regularizado
Interpretacion MMSE: LMMSE simplificado por regularizacion
Ecualizador final: MMSE escalar
LMMSE completo con covarianzas: no implementado actualmente
```

Esta distincion es importante para explicar bien el simulador: se usa una idea
matematica cercana a LMMSE en la estimacion del canal y un MMSE escalar en la
ecualizacion, pero no se implementa un receptor LMMSE completo con estadisticas
detalladas del canal.
