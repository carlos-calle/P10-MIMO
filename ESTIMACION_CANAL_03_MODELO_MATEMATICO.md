# Estimacion de canal 03 - Modelo matematico

Este archivo profundiza en el modelo matematico usado por el simulador desde
las portadoras piloto hasta la ecualizacion.

## 1. Modelo OFDM por subportadora

Despues de retirar el prefijo ciclico y aplicar FFT, el modelo ideal de OFDM es:

```text
Y_b[k] = H[k] X_b[k] + W_b[k]
```

donde:

- `Y_b[k]` es la subportadora recibida en el bloque `b`.
- `X_b[k]` es el simbolo transmitido en esa subportadora.
- `H[k]` es la respuesta del canal en frecuencia.
- `W_b[k]` es ruido.

Si el CP es suficientemente largo, la convolucion lineal del canal se observa
como una multiplicacion por subportadora. Esa es la gran ventaja de OFDM.

## 2. Pilotos

En algunas posiciones `k_p`, el transmisor no envia datos de imagen, sino
pilotos conocidos:

```text
X_b[k_p] = P_b[k_p]
```

El receptor conoce esos pilotos porque se generan deterministicamente con:

```python
pilot_symbol_grid(num_blocks, num_pilots, pilot_seed)
```

Entonces, en una posicion piloto:

```text
Y_b[k_p] = H[k_p] P_b[k_p] + W_b[k_p]
```

## 3. Estimacion LS en las posiciones piloto

La estimacion LS de `H[k_p]` minimiza:

```text
|Y_b[k_p] - H[k_p] P_b[k_p]|^2
```

Derivando respecto a `H[k_p]`, la solucion es:

```text
H_LS[k_p] = Y_b[k_p] / P_b[k_p]
```

En el codigo:

```python
h_ls = active_grid[block_idx, pilot_mask] / pilots[block_idx]
```

Como los pilotos QPSK tienen modulo unitario, dividir por el piloto equivale a
corregir amplitud y fase respecto al simbolo conocido.

## 4. Patron escalonado de pilotos

El programa usa un patron base cada 6 subportadoras:

```text
PILOT_SPACING_SC = 6
```

Pero alterna el desplazamiento:

```text
bloque par:   offset = 0
bloque impar: offset = 3
```

Matematicamente, una subportadora es piloto si:

```text
(k - offset_b) mod 6 = 0
```

En codigo:

```python
return ((np.arange(nc) - offset) % pilot_spacing) == 0
```

Esto crea una malla efectiva mas densa si el canal no cambia rapidamente en el
tiempo.

## 5. Promedio temporal

Como el simulador genera una misma realizacion de canal para toda una
transmision, se puede asumir:

```text
H_b[k] = H[k]
```

para todos los bloques `b`.

Por eso, si una misma subportadora piloto se observa varias veces, se promedia:

```text
H_prom[k] = (1 / N_k) sum_b H_LS,b[k]
```

En codigo:

```python
sum_h[pilot_indices] += h_ls
count_h[pilot_indices] += 1
h_known = sum_h[known_indices] / count_h[known_indices]
```

Si el ruido es de media cero, este promedio reduce la varianza del ruido de
estimacion aproximadamente en un factor `N_k`.

## 6. Pasar del dominio frecuencia al dominio tiempo

El canal multipath tiene una respuesta impulsiva:

```text
h[0], h[1], ..., h[L-1]
```

Su respuesta en frecuencia es la DFT:

```text
H[k] = sum_{l=0}^{L-1} h[l] e^{-j 2 pi k l / N}
```

El estimador del codigo usa esta relacion al reves. Tiene algunas muestras
`H[k_p]` en pilotos y quiere estimar los taps `h[l]`.

Para las posiciones piloto:

```text
H[k_p] = sum_{l=0}^{L-1} h[l] e^{-j 2 pi k_p l / N}
```

Esto se escribe en forma matricial:

```text
y = A h + w
```

donde:

- `y` contiene las estimaciones de canal en pilotos.
- `A` contiene exponenciales complejas.
- `h` contiene los taps del canal.
- `w` representa error de estimacion y ruido.

En el codigo, `A` se llama `basis`:

```python
basis = np.exp(-2j * np.pi * pilot_bins[:, None] * taps[None, :] / n_fft)
```

## 7. LS puro

Si se quisiera resolver por LS puro:

```text
h_LS = arg min_h ||y - A h||^2
```

La solucion es:

```text
h_LS = (A^H A)^(-1) A^H y
```

Esto funciona bien si `A^H A` esta bien condicionado y si el ruido no causa
problemas.

## 8. LS regularizado

El codigo usa una version regularizada:

```text
h_reg = (A^H A + lambda I)^(-1) A^H y
```

En codigo:

```python
gram = basis.conj().T @ basis
weights = np.linalg.solve(gram + ridge * np.eye(tap_count), basis.conj().T)
h_taps = weights @ h_known
```

El termino `lambda I` evita que la solucion dependa demasiado de componentes
inestables. Esta tecnica tambien se conoce como regularizacion de Tikhonov o
ridge regression.

## 9. Reconstruccion de la respuesta en frecuencia

Luego de obtener `h_taps`, el programa construye:

```python
h_time = np.zeros(n_fft, dtype=np.complex128)
h_time[:tap_count] = h_taps
h_active = np.fft.fft(h_time)[active_subcarrier_indices(n_fft, nc)]
```

Matematicamente:

```text
H_est[k] = DFT{h_reg}[k]
```

Asi el receptor obtiene una estimacion `H_est[k]` para cada subportadora activa,
incluidas las que no eran piloto.

## 10. Ecualizacion Zero-Forcing

Con `H_est[k]`, el codigo ecualiza:

```python
equalized_grid = active_grid / h_est
```

La formula es:

```text
X_ZF[k] = Y[k] / H_est[k]
```

Esta tecnica se llama Zero-Forcing porque intenta invertir el canal por completo.

El riesgo es que si `|H_est[k]|` es muy pequeno, la division amplifica el ruido.
Por eso el codigo protege:

```python
small = np.abs(h_est) < threshold
h_est[small] = threshold + 0j
```

## 11. Ecualizacion MMSE

Un ecualizador MMSE no invierte el canal de forma tan agresiva. Su forma tipica
por subportadora es:

```text
G_MMSE[k] = H_est^*[k] / (|H_est[k]|^2 + sigma_w^2 / sigma_x^2)
```

y:

```text
X_MMSE[k] = G_MMSE[k] Y[k]
```

Si el ruido es bajo:

```text
sigma_w^2 / sigma_x^2 -> 0
```

entonces:

```text
G_MMSE[k] -> 1 / H_est[k]
```

Es decir, MMSE se parece a ZF a SNR alta.

Si el ruido es alto o `|H_est[k]|` es pequeno, MMSE evita amplificar demasiado
el ruido.

## 12. Que implementa exactamente el programa

El programa implementa:

```text
Estimacion en pilotos: LS
Promedio temporal: si
Reconstruccion de canal: DFT/LS regularizado
Ecualizacion final: ZF
MMSE completo: no
```

La parte mas cercana a MMSE es:

```text
(A^H A + lambda I)^(-1) A^H
```

porque la regularizacion cumple un papel parecido al termino de ruido en MMSE:
reduce soluciones extremas y mejora estabilidad.

