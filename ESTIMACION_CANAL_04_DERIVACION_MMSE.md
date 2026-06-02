# Estimacion de canal 04 - Derivacion LS, regularizacion y MMSE

Este archivo profundiza en la relacion entre LS, LS regularizado, MMSE y la
ecualizacion usada por el programa.

## 1. Modelo estadistico base

En frecuencia, luego de FFT:

```text
Y[k] = H[k] X[k] + W[k]
```

Asumimos:

```text
E[W[k]] = 0
E[|W[k]|^2] = sigma_w^2
E[|X[k]|^2] = sigma_x^2
```

En pilotos:

```text
Y_p[k] = H[k] P[k] + W[k]
```

Como `P[k]` es conocido:

```text
H_LS[k] = Y_p[k] / P[k]
```

Si los pilotos tienen modulo unitario:

```text
E[|Y_p/P - H|^2] = sigma_w^2
```

Es decir, la calidad de la estimacion LS depende directamente del ruido.

## 2. Problema de interpolar H[k]

Con pilotos solo conocemos `H[k]` en algunas subportadoras. Si se hiciera
interpolacion lineal pura, se asumiria que entre pilotos el canal cambia de
forma suave.

Pero un canal con eco retardado produce:

```text
H[k] = h_0 + h_1 e^{-j 2 pi k tau / T}
```

Ese termino oscilatorio puede cambiar rapido en frecuencia. Por eso el codigo
usa una reconstruccion basada en taps temporales.

## 3. Modelo matricial de pilotos

Sea `Kp` el conjunto de subportadoras piloto conocidas. Para cada piloto:

```text
H[k_p] = sum_{l=0}^{L-1} h[l] e^{-j 2 pi k_p l / N}
```

Definimos:

```text
y = [H[k_1], H[k_2], ..., H[k_M]]^T
h = [h[0], h[1], ..., h[L-1]]^T
```

La matriz `A` queda:

```text
A[m, l] = e^{-j 2 pi k_m l / N}
```

Entonces:

```text
y = A h + n
```

En codigo:

```python
basis = np.exp(-2j * np.pi * pilot_bins[:, None] * taps[None, :] / n_fft)
```

## 4. LS puro

El estimador LS puro resuelve:

```text
min_h ||y - A h||_2^2
```

La solucion se obtiene imponiendo las ecuaciones normales:

```text
A^H A h = A^H y
```

Por tanto:

```text
h_LS = (A^H A)^(-1) A^H y
```

Si `A^H A` es singular o esta mal condicionada, la solucion puede ser muy
ruidosa.

## 5. LS regularizado o Tikhonov

El codigo resuelve una version penalizada:

```text
min_h ||y - A h||_2^2 + lambda ||h||_2^2
```

Esta funcion costo tiene dos terminos:

- `||y - A h||_2^2`: obliga a ajustar los pilotos.
- `lambda ||h||_2^2`: evita taps excesivamente grandes.

Derivando e igualando a cero:

```text
A^H A h + lambda h = A^H y
```

Por tanto:

```text
h_reg = (A^H A + lambda I)^(-1) A^H y
```

En el codigo:

```python
gram = basis.conj().T @ basis
weights = np.linalg.solve(gram + ridge * np.eye(tap_count), basis.conj().T)
h_taps = weights @ h_known
```

Con:

```python
ridge = CHANNEL_ESTIMATION_RIDGE = 1e-2
```

## 6. Interpretacion tipo MAP/MMSE

La regularizacion se puede interpretar estadisticamente. Supongamos:

```text
n ~ CN(0, sigma_w^2 I)
h ~ CN(0, sigma_h^2 I)
```

Entonces el estimador MAP de `h` minimiza:

```text
(1/sigma_w^2) ||y - A h||^2 + (1/sigma_h^2) ||h||^2
```

Multiplicando por `sigma_w^2`:

```text
||y - A h||^2 + (sigma_w^2 / sigma_h^2) ||h||^2
```

Por comparacion:

```text
lambda = sigma_w^2 / sigma_h^2
```

Asi, el LS regularizado coincide con una forma simple de estimacion tipo
MMSE/MAP cuando se asumen covarianzas diagonales e isotropicas.

Esta es la razon por la que la regularizacion se parece a MMSE: introduce una
penalizacion relacionada con ruido y potencia esperada del canal.

## 7. LMMSE general de canal

El estimador LMMSE general para:

```text
y = A h + n
```

con:

```text
R_hh = E[h h^H]
R_nn = E[n n^H]
```

es:

```text
h_LMMSE = R_hh A^H (A R_hh A^H + R_nn)^(-1) y
```

Si:

```text
R_hh = sigma_h^2 I
R_nn = sigma_w^2 I
```

entonces:

```text
h_LMMSE = (A^H A + sigma_w^2/sigma_h^2 I)^(-1) A^H y
```

que coincide con la forma ridge usada por el codigo.

La diferencia es que el programa no estima `sigma_w^2`, `sigma_h^2` ni una
matriz `R_hh` realista. Usa un `lambda` fijo.

## 8. Reconstruccion de H[k]

Despues de estimar `h_reg`, se calcula:

```text
H_est[k] = sum_{l=0}^{L-1} h_reg[l] e^{-j 2 pi k l / N}
```

En codigo:

```python
h_time[:tap_count] = h_taps
h_active = np.fft.fft(h_time)[active_subcarrier_indices(n_fft, nc)]
```

Esto convierte el canal estimado en tiempo a respuesta en frecuencia sobre las
subportadoras activas.

## 9. Ecualizacion MMSE por subportadora

El programa ecualiza con una forma MMSE escalar:

```text
X_MMSE[k] = G_MMSE[k] Y[k]
```

El ecualizador MMSE busca minimizar:

```text
E[|X[k] - G[k] Y[k]|^2]
```

Sabiendo que:

```text
Y[k] = H[k] X[k] + W[k]
```

la solucion escalar es:

```text
G_MMSE[k] = sigma_x^2 H^*[k] / (sigma_x^2 |H[k]|^2 + sigma_w^2)
```

Dividiendo por `sigma_x^2`:

```text
G_MMSE[k] = H^*[k] / (|H[k]|^2 + sigma_w^2 / sigma_x^2)
```

En el codigo, el termino:

```text
noise_to_signal
```

representa esa razon `sigma_w^2 / sigma_x^2`.

## 10. Zero-Forcing como caso limite

ZF seria:

```text
G_ZF[k] = 1 / H[k] = H^*[k] / |H[k]|^2
```

Cuando `sigma_w^2` es muy pequeno:

```text
G_MMSE[k] approx G_ZF[k]
```

La diferencia es que MMSE no cancela el canal de forma tan agresiva cuando
`|H[k]|` es pequeno; por eso evita amplificar tanto el ruido.

Si definimos:

```text
gamma = sigma_x^2 / sigma_w^2
```

entonces:

```text
G_MMSE[k] = H^*[k] / (|H[k]|^2 + 1/gamma)
```

## 11. Estado exacto del programa

El programa actualmente hace:

```text
Pilotos:
  H_LS = Y_p / P

Canal:
  h_reg = (A^H A + lambda I)^(-1) A^H H_LS
  H_est = FFT(h_reg)

Ecualizacion:
  X_est = H_est^* Y / (|H_est|^2 + noise_to_signal)
```

Esto es:

- LS en pilotos.
- Estimacion DFT/LS regularizada de canal.
- Ecualizacion MMSE escalar.

La parte regularizada puede entenderse como una version simplificada de LMMSE
si se interpreta `lambda` como una relacion ruido/potencia del canal.
