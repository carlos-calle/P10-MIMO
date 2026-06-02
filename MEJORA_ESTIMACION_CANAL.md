# Mejora de estimacion de canal

Este archivo documenta el cambio aplicado para que el simulador pueda mostrar
el efecto del prefijo ciclico sin depender de pilotos cada 2 subportadoras.

## Problema observado

Con el perfil `Didactico CP`, el eco principal esta a `12 us`. Ese retardo
produce un rizado rapido en frecuencia. Si los pilotos quedan demasiado
separados y la recepcion solo interpola linealmente, el error de estimacion de
canal domina la BER. En ese caso, el receptor falla por la estimacion de canal
antes de que se pueda observar claramente la diferencia entre CP normal y CP
extendido.

La solucion temporal de usar `PILOT_SPACING_SC = 2` funcionaba, pero era poco
representativa: aumentaba mucho el overhead de pilotos y se alejaba del valor
de referencia CRS LTE de 6 subportadoras.

## Solucion implementada

La mejora queda en tres partes:

1. `core/config.py`

```python
LTE_CRS_REFERENCE_SPACING_SC = 6
PILOT_SPACING_SC = LTE_CRS_REFERENCE_SPACING_SC
PILOT_STAGGER_OFFSET_SC = PILOT_SPACING_SC // 2
PILOT_STAGGER_ENABLED = True
CHANNEL_ESTIMATION_RIDGE = 1e-2
```

El espaciamiento base vuelve a ser 6 subportadoras. Para no perder resolucion
en frecuencia, el patron se escalona: un bloque OFDM usa offset 0 y el siguiente
usa offset 3. Asi, con dos bloques consecutivos se obtiene una malla efectiva
mas densa sin convertir todos los simbolos en pilotos.

2. `core/ofdm_ops.py`

La mascara de pilotos ahora depende del indice de bloque:

```python
offset = _pilot_offset(block_idx, pilot_spacing, staggered)
return ((np.arange(nc) - offset) % pilot_spacing) == 0
```

La modulacion OFDM inserta pilotos por bloque con `pilot_subcarrier_masks`.
La demodulacion promedia las observaciones LS de pilotos en el tiempo, porque
el canal del simulador es constante durante una transmision.

3. Estimacion DFT/LS regularizada

En recepcion se estima primero el canal en pilotos:

```python
H_p = Y_p / X_p
```

Luego se ajusta un canal en dominio temporal con soporte finito:

```python
h_taps = weights @ h_known
h_active = np.fft.fft(h_time)[active_subcarrier_indices(n_fft, nc)]
```

La regularizacion `CHANNEL_ESTIMATION_RIDGE = 1e-2` evita que el ajuste LS
sobreamplifique ruido cuando el soporte temporal del canal es largo. Esto es la
parte clave: no solo interpola entre pilotos, sino que usa la idea fisica de que
un canal multipath vive en pocos taps temporales y despues reconstruye su
respuesta en frecuencia.

## Por que no se uso interpolacion cubica

Una interpolacion cubica puede suavizar mejor que la lineal, pero no resuelve el
problema principal si la respuesta en frecuencia fue submuestreada por los
pilotos. El cambio definitivo fue usar estructura OFDM: pilotos escalonados,
promedio temporal y estimacion en dominio temporal. Eso esta mas alineado con
un receptor LTE simplificado que solo cambiar el interpolador.

## Resultado esperado

Escenario de prueba:

- Imagen: `imagenes/cameraman.jpg`
- Perfil de canal: `Didactico CP`
- Ancho de banda: `20 MHz`
- Caminos: `2`
- SNR: `30 dB`
- Pilotos: base cada 6 subportadoras, escalonados 0/3

Resultado medido despues del cambio:

```text
QPSK
  CP Normal    BER=0.000018
  CP Extendido BER=0.000000
16-QAM
  CP Normal    BER=0.011520
  CP Extendido BER=0.000000
64-QAM
  CP Normal    BER=0.071138
  CP Extendido BER=0.000000
```

La lectura importante es que el CP extendido vuelve a comportarse como predice
la teoria para este perfil: cubre el eco de `12 us` y elimina la ISI apreciable.
El CP normal no cubre ese eco y conserva BER, especialmente en modulaciones de
mayor orden.

## Archivos modificados

- `core/config.py`: parametros del patron de pilotos y regularizacion.
- `core/ofdm_ops.py`: pilotos escalonados, promedio temporal y estimacion
  DFT/LS regularizada.
- `controller/simulation_mgr.py`: la recepcion pasa a la estimacion de canal el
  numero de taps del canal simulado.
- `tests/test_core.py`: pruebas actualizadas para el nuevo patron de pilotos.
- `PAPR.md`, `FLUJO_IMAGEN.md`, `PARTES_IMPORTANTES_SIMULADOR.md`,
  `README.md`: referencias actualizadas para dejar de describir pilotos cada 2.

## Limitacion

La estimacion usa el largo del canal simulado como soporte temporal. Eso es
razonable para este simulador didactico, porque el receptor trabaja sobre un
modelo de canal conocido. En un receptor real se estimaria o acotaria ese
soporte con filtros de canal, sincronizacion y estadistica del PDP.
