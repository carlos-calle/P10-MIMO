# Aclaraciones De Estimacion De Canal (FAQ Practica)

Este documento resume, en formato de dudas frecuentes, los puntos que suelen confundirse al leer la estimacion de canal del simulador.

Archivos clave del flujo:

- [core/ofdm_ops.py](core/ofdm_ops.py)
- [controller/simulation_mgr.py](controller/simulation_mgr.py)
- [core/config.py](core/config.py)
- [core/channel.py](core/channel.py)

## 1) Donde empieza la estimacion de canal

La estimacion comienza al comparar pilotos recibidos vs pilotos conocidos:

$$
\hat{H}_{LS} = \frac{Y_{pilot}}{X_{pilot}}
$$

En codigo, esa division aparece en `core/ofdm_ops.py` dentro de `_average_pilot_observations`.

Importante: esta division se hace en dominio frecuencia (subportadoras), no en dominio tiempo.

## 2) Que hace exactamente `_average_pilot_observations`

Hace tres cosas:

1. Calcula LS en cada piloto observado: `Y/X`.
2. Acumula estimaciones por indice de subportadora.
3. Promedia cuando la misma subportadora fue observada varias veces en distintos bloques.

Salida:

- `known_indices`: posiciones con observacion valida.
- `h_known`: estimacion promedio en esas posiciones.

## 3) Patron de pilotos: por que 0,6,12... y luego 3,9,15...

Lo definen las constantes en `core/config.py`:

- `PILOT_SPACING_SC = 6`
- `PILOT_STAGGER_OFFSET_SC = 3`
- `PILOT_STAGGER_ENABLED = True`

Con eso:

- bloque par: 0, 6, 12, ...
- bloque impar: 3, 9, 15, ...

Este escalonamiento densifica la malla efectiva de estimacion sin aumentar demasiado overhead.

## 4) Que son `temporal_average` y `max_channel_taps`

Son parametros de `demodulate_ofdm_with_pilots`:

- `temporal_average` (default `True`) decide si se fusiona informacion entre bloques.
- `max_channel_taps` decide cuantas variables temporales (taps) permite estimar la rama LS temporal.

Ramas:

1. `temporal_average=True` y `max_channel_taps` no `None`:
   usa LS temporal (estimacion de taps).
2. `temporal_average=True` y `max_channel_taps=None`:
   usa promedio + interpolacion.
3. `temporal_average=False`:
   estima por bloque sin promedio temporal.

## 5) Que es un tap

Un tap es un coeficiente complejo del canal en dominio tiempo (un eco discreto del multipath).

Si el canal tiene L taps, la respuesta impulsiva es:

$$
h[0], h[1], \dots, h[L-1]
$$

Y la respuesta en frecuencia se obtiene por FFT de esa respuesta impulsiva.

## 6) Donde entran minimos cuadrados

En la funcion `_estimate_channel_from_time_domain_ls` de `core/ofdm_ops.py`.

Primero se obtiene `h_known` (observaciones en pilotos), luego se resuelve una LS regularizada para estimar taps:

$$
\hat{\mathbf h} = \arg\min_{\mathbf h}\|\mathbf y - \mathbf A\mathbf h\|^2 + \lambda\|\mathbf h\|^2
$$

En codigo:

1. `weights = _time_domain_ls_weights(...)`
2. `h_taps = weights @ h_known`

Esa multiplicacion matricial estima todos los taps a la vez.

## 7) Es iterativo o directo

En esta implementacion es directo (closed-form), no por iteraciones de optimizacion.

Se hace algebra lineal (matrices) en una pasada para resolver LS/ridge.

## 8) A cuantas subportadoras afecta el resultado LS temporal

LS temporal estima taps, y desde ellos reconstruye `H[k]` por FFT para todas las subportadoras activas.

Luego la ecualizacion divide toda la grilla activa por esa estimacion, y al final se extraen solo las subportadoras de datos.

## 9) Las subportadoras contiguas tienen el mismo canal

No necesariamente.

- Suelen ser parecidas si el canal es suave en frecuencia.
- No tienen por que ser iguales.

Esto depende de la fisica del canal (delay spread, multipath), no de que el metodo sea LS o interpolacion lineal.

## 10) Se usa el canal real o se estima

En el flujo principal de recepcion se estima con pilotos (`demodulate_ofdm_with_pilots`).

No se ecualiza directamente con el canal real en esa ruta.

Punto fino: se usa `len(h_used)` como pista para `max_channel_taps`, lo que ayuda al estimador con una informacion estructural (longitud esperada del canal).

## 11) `equalize_channel` vs `demodulate_ofdm_with_pilots`

- `equalize_channel` espera respuesta impulsiva en tiempo (`h_impulse_response`) y ecualiza directo por FFT.
- `demodulate_ofdm_with_pilots` estima canal a partir de pilotos y luego ecualiza.

La ruta principal del manager usa `demodulate_ofdm_with_pilots`.

## 12) Relacion con LTE real

La idea base si es LTE-realista: usar referencias conocidas para estimar canal y ecualizar.

Lo simplificado en este simulador es:

- patron de pilotos didactico fijo,
- perfil didactico de canal,
- modelo SISO limpio para docencia,
- menos complejidad que una implementacion LTE completa.

## 13) Resumen de una linea

El receptor usa pilotos conocidos para obtener observaciones LS en frecuencia, fusiona esa informacion y, opcionalmente, ajusta taps en tiempo con LS regularizado para reconstruir `H[k]` y ecualizar los datos.