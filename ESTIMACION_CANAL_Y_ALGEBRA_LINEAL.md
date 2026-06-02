# Estimacion De Canal Y Algebra Lineal En El Simulador

Este documento explica con detalle la parte de estimacion de canal del simulador y, sobre todo, el algebra lineal que hay detras. La idea es conectar lo que hace el codigo con la teoria: desde la division simple en pilotos hasta la reconstruccion del canal mediante minimos cuadrados regularizados en dominio temporal.

Archivos principales relacionados:

- [core/ofdm_ops.py](core/ofdm_ops.py)
- [core/channel.py](core/channel.py)
- [controller/simulation_mgr.py](controller/simulation_mgr.py)
- [core/config.py](core/config.py)

## 1. Idea General

En OFDM, el canal en dominio frecuencia se representa como una ganancia compleja distinta en cada subportadora:

$$
Y[k] = H[k] X[k] + N[k]
$$

donde:

- $X[k]$ es el simbolo transmitido en la subportadora $k$,
- $Y[k]$ es el simbolo recibido,
- $H[k]$ es la respuesta del canal en frecuencia,
- $N[k]$ es ruido.

Si el receptor conociera exactamente $H[k]$, podria ecualizar haciendo:

$$
\hat X[k] = \frac{Y[k]}{H[k]}
$$

Pero como $H[k]$ no se conoce, hay que estimarlo.

## 2. Como Empieza La Estimacion En Este Proyecto

La primera aproximacion del canal se obtiene en los pilotos. Como el transmisor conoce los pilotos enviados y el receptor tambien, se puede usar una estimacion LS elemental:

$$
\hat H_{LS}(k_p) = \frac{Y(k_p)}{X(k_p)}
$$

Esta es la primera estimacion del canal. En el codigo aparece dentro de `_average_pilot_observations(...)` en [core/ofdm_ops.py](core/ofdm_ops.py):

```python
h_ls = active_grid[block_idx, pilot_mask] / pilots[block_idx]
```

Importante:

- esta division se hace en dominio frecuencia,
- solo existe en las posiciones de los pilotos,
- todavia no es el canal completo de todas las subportadoras activas.

## 3. El Papel De Los Pilotos

Los pilotos estan definidos de forma determinista y con patron fijo. En este simulador:

- hay un piloto cada 6 subportadoras activas,
- los bloques alternan el patron entre `0, 6, 12, ...` y `3, 9, 15, ...`,
- los simbolos piloto son QPSK deterministas generados con semilla fija.

Esto se controla desde [core/config.py](core/config.py) y se aplica en [core/ofdm_ops.py](core/ofdm_ops.py).

La razon de este patron escalonado es que el receptor pueda observar mas posiciones del canal al combinar varios simbolos OFDM.

## 4. Que Hace `_average_pilot_observations`

La funcion `_average_pilot_observations(...)` en [core/ofdm_ops.py](core/ofdm_ops.py) toma las estimaciones LS puntuales y construye un conjunto de observaciones mas robusto.

Flujo:

1. Para cada bloque OFDM, identifica las posiciones piloto.
2. Calcula $Y/X$ en esas posiciones.
3. Acumula esas observaciones en `sum_h`.
4. Cuenta cuantas veces se observo cada subportadora en `count_h`.
5. Promedia cuando una misma subportadora fue observada varias veces.

El resultado es:

- `known_indices`: posiciones donde si hay informacion del canal.
- `h_known`: estimacion promedio del canal en esas posiciones.

En otras palabras, `h_known` es el vector de observaciones del canal que luego alimenta la parte de algebra lineal.

## 5. Las Tres Ramas De Estimacion En El Receptor

La funcion central es `demodulate_ofdm_with_pilots(...)` en [core/ofdm_ops.py](core/ofdm_ops.py).

Tiene tres ramas principales:

### 5.1 Raza 1: LS temporal con taps y ridge

Se usa cuando:

- `temporal_average=True`
- `max_channel_taps` no es `None`

Esta es la rama mas fuerte del simulador y la mas cargada de algebra lineal.

### 5.2 Rama 2: promedio + interpolacion

Se usa cuando:

- `temporal_average=True`
- `max_channel_taps=None`

Aqui no se estiman taps, solo se interpola desde observaciones `h_known`.

### 5.3 Rama 3: estimacion por bloque

Se usa cuando:

- `temporal_average=False`

Se estima por bloque en frecuencia, sin fusion temporal global.

## 6. La Rama Mas Importante: LS Temporal En Dominio Tiempo

La funcion es `_estimate_channel_from_time_domain_ls(...)` en [core/ofdm_ops.py](core/ofdm_ops.py).

Su objetivo no es estimar directamente todas las subportadoras una por una, sino estimar primero los **taps del canal** en tiempo y luego reconstruir la respuesta en frecuencia con FFT.

### 6.1 Que es un tap

Un tap es un coeficiente complejo de la respuesta impulsiva del canal discreto:

$$
h[0], h[1], h[2], \dots, h[L-1]
$$

Cada tap representa un eco del canal con cierto retardo y cierta ganancia/fase.

Si el canal tiene pocos taps, entonces su comportamiento en frecuencia se puede explicar con pocos parametros. Esa es la razon de modelarlo asi.

## 7. Algebra Lineal: El Modelo Del Canal

La relacion entre taps en tiempo y respuesta en frecuencia viene dada por la DFT:

$$
H[k] = \sum_{l=0}^{L-1} h[l] e^{-j 2\pi k l / N}
$$

Si solo observas el canal en ciertas subportadoras piloto $k_1, k_2, \dots, k_K$, puedes escribir el problema como:

$$
\mathbf y = \mathbf A \mathbf h + \mathbf n
$$

donde:

- $\mathbf y$ es el vector de observaciones del canal en pilotos,
- $\mathbf h$ es el vector de taps desconocidos,
- $\mathbf A$ es la matriz base construida con las exponenciales complejas,
- $\mathbf n$ es ruido/error de modelado.

En el simulador:

- $\mathbf y$ corresponde a `h_known`,
- $\mathbf A$ corresponde a `basis`,
- $\mathbf h$ corresponde a `h_taps`.

## 8. Construccion De La Matriz Base `basis`

La funcion `_time_domain_ls_weights(...)` construye la matriz del modelo. En codigo:

```python
basis = np.exp(-2j * np.pi * pilot_bins[:, None] * taps[None, :] / n_fft)
```

Esto crea una matriz de tamano:

$$
K \times L
$$

donde:

- $K$ es el numero de observaciones piloto validas,
- $L$ es `tap_count`, el numero de taps a estimar.

Cada fila corresponde a una subportadora piloto observada. Cada columna corresponde a un tap posible.

Fisicamente, la matriz dice: “si el canal tuviera estos taps, asi se verian esos pilotos en frecuencia”.

## 9. Que Es `weights`

`weights` es la matriz del estimador LS regularizado.

No es el canal. No son los taps. No son las observaciones.

Es el operador lineal que transforma observaciones piloto en taps estimados.

Matematicamente:

$$
\mathbf W = (\mathbf A^H \mathbf A + \lambda \mathbf I)^{-1} \mathbf A^H
$$

En el codigo, eso se construye en [core/ofdm_ops.py](core/ofdm_ops.py):

```python
gram = basis.conj().T @ basis
return np.linalg.solve(gram + ridge * np.eye(tap_count), basis.conj().T)
```

Si `ridge == 0`, usa pseudoinversa:

$$
\mathbf W = \mathbf A^+
$$

### 9.1 Por que `weights` tiene informacion util

Porque encapsula toda la geometria del problema:

- donde estan las subportadoras piloto observadas,
- cuantas observaciones hay,
- cuantos taps quieres estimar,
- como esos taps se proyectan en frecuencia,
- cuanto quieres regularizar.

Entonces `weights` es como un traductor fijo entre dos espacios:

- espacio de observaciones en pilotos,
- espacio de taps del canal.

## 10. Que Es Ridge

Ridge es una regularizacion que evita soluciones inestables. Cambia el problema de:

$$
\min_{\mathbf h} \|\mathbf y - \mathbf A \mathbf h\|^2
$$

a:

$$
\min_{\mathbf h} \|\mathbf y - \mathbf A \mathbf h\|^2 + \lambda \|\mathbf h\|^2
$$

Esto penaliza taps demasiado grandes o soluciones numericamente inestables.

Intuicion:

- sin ridge: ajusta fuerte, pero puede exagerar por ruido,
- con ridge: ajusta bien, pero mantiene una solucion mas razonable.

## 11. La Multiplicacion Clave: `h_taps = weights @ h_known`

Esta es una de las lineas mas importantes del receptor.

Aqui se aplica el estimador lineal:

$$
\hat{\mathbf h} = \mathbf W \mathbf y
$$

En el codigo:

- `weights` = $\mathbf W$
- `h_known` = $\mathbf y$
- `h_taps` = $\hat{\mathbf h}$

Dimensiones tipicas:

- `weights`: $L \times K$
- `h_known`: $K \times 1$
- `h_taps`: $L \times 1$

Es decir: con una sola multiplicacion matricial se estiman todos los taps a la vez.

## 12. Que Pasa Despues De Obtener `h_taps`

Una vez estimados los taps:

1. Se crea un vector temporal `h_time` de longitud `n_fft` lleno de ceros.
2. Se colocan los taps estimados al inicio:

```python
h_time[:tap_count] = h_taps
```

3. Se hace FFT para obtener respuesta en frecuencia:

```python
h_active = np.fft.fft(h_time)[active_subcarrier_indices(n_fft, nc)]
```

4. Se replica ese canal estimado para todos los bloques OFDM:

```python
return np.tile(h_active, (active_grid.shape[0], 1))
```

Resultado final: un `H[k]` estimado para todas las subportadoras activas de cada bloque.

## 13. Como Se Usa Ese Canal Estimado

En `demodulate_ofdm_with_pilots(...)`, el canal estimado `h_est` se usa para ecualizar:

```python
equalized_grid = active_grid / h_est
```

Despues se extraen solo las subportadoras de datos, quitando los pilotos.

## 14. Es Iterativo O Directo

En esta implementacion no es un metodo iterativo de optimizacion.

No prueba canales uno por uno. No hace gradiente descendente.

Hace una resolucion directa de algebra lineal:

1. construye $A$,
2. construye $W$,
3. calcula $\hat h = W y$.

Por eso el metodo es rapido y limpio de implementar.

## 15. Por Que Esta Rama Es “Optimista”

En el flujo actual del simulador, la rama temporal se usa casi siempre con una pista adicional: `max_channel_taps = len(h_used)` desde el manager.

Eso significa que el receptor sabe cuanta longitud tiene el canal real simulado. No usa el canal real completo para ecualizar, pero si usa esa pista estructural.

Eso vuelve la estimacion mas favorable que en un receptor totalmente ciego.

## 16. Si No Se Usara LS Temporal

Si el codigo no entrara a la rama LS temporal, entonces usaria:

- interpolacion lineal desde pilotos, o
- estimacion por bloque.

Esas ramas usan menos algebra lineal y mas geometria/interpolacion en frecuencia.

## 17. La Relacion Entre Telecomunicaciones Y Algebra Lineal Aqui

Esta parte del proyecto mezcla dos mundos:

### 17.1 Telecomunicaciones y procesamiento de señales

- OFDM
- FFT/IFFT
- prefijo ciclico
- respuesta impulsiva del canal
- respuesta en frecuencia
- pilotos y ecualizacion

### 17.2 Algebra lineal

- vectores y matrices
- producto matricial
- traspuesta conjugada
- pseudoinversa
- resolucion de sistemas lineales
- regularizacion ridge
- proyeccion lineal de observaciones a parametros

## 18. Resumen Intuitivo Final

El flujo de la rama fuerte del estimador es este:

1. El receptor mira los pilotos recibidos.
2. Hace una primera estimacion simple con $Y/X$.
3. Promedia observaciones y forma `h_known`.
4. Construye una matriz que modela como se ven los taps en los pilotos.
5. Usa minimos cuadrados regularizados para encontrar los taps que mejor explican esas observaciones.
6. Convierte esos taps a frecuencia con FFT.
7. Usa el canal estimado para ecualizar toda la grilla activa.

En una frase:

**la parte de algebra lineal sirve para transformar unas pocas observaciones ruidosas del canal en pilotos en una estimacion global y estructurada del canal completo.**

## 19. Mapa Rapido De Variables

- `active_grid`: simbolos recibidos en subportadoras activas
- `pilots`: pilotos conocidos enviados
- `h_ls`: estimacion local Y/X en pilotos
- `h_known`: estimacion promedio en subportadoras observadas
- `basis`: matriz del modelo lineal
- `weights`: operador LS/ridge
- `h_taps`: taps estimados en tiempo
- `h_time`: respuesta impulsiva embebida en longitud FFT
- `h_active`: canal estimado en frecuencia sobre subportadoras activas
- `h_est`: canal final usado para ecualizar

## 20. Cierre

Si el proyecto se mira solo como simulador OFDM, parece que “solo divide por el canal”. Pero la parte mas interesante es que, antes de ecualizar, construye un problema de estimacion estructurado y lo resuelve con algebra lineal. Esa es la parte que realmente convierte una estimacion puntual en pilotos en una reconstruccion coherente del canal.