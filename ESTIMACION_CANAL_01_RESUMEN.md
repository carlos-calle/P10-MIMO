# Estimacion de canal 01 - Resumen superficial

Este archivo explica de forma general como el programa estima el canal usando
portadoras piloto y como despues ecualiza los datos recibidos.

## Idea principal

En una transmision OFDM, cada simbolo se reparte en muchas subportadoras. El
canal no afecta igual a todas: algunas subportadoras pueden atenuarse, otras
pueden cambiar de fase y otras pueden quedar casi sin cambio.

Para corregir eso, el transmisor inserta simbolos conocidos llamados pilotos.
Como el receptor sabe que valor debia tener cada piloto, puede comparar:

```text
piloto recibido vs piloto transmitido
```

Con esa comparacion estima cuanto modifico el canal a la senal.

## Donde ocurre en el codigo

El flujo principal esta en:

- `controller/simulation_mgr.py`
- `core/ofdm_ops.py`
- `core/config.py`

Los parametros de pilotos estan en `core/config.py`:

```python
PILOT_SPACING_SC = LTE_CRS_REFERENCE_SPACING_SC
PILOT_STAGGER_OFFSET_SC = PILOT_SPACING_SC // 2
PILOT_STAGGER_ENABLED = True
CHANNEL_ESTIMATION_RIDGE = 1e-2
```

Esto significa:

- Se usa una separacion base de 6 subportadoras.
- El patron de pilotos se desplaza entre bloques OFDM.
- Se usa una regularizacion numerica al estimar el canal.

## Transmision con pilotos

La funcion principal es:

```python
modulate_ofdm_with_pilots(...)
```

Esta funcion hace tres cosas:

1. Separa posiciones de datos y posiciones de pilotos.
2. Inserta pilotos QPSK conocidos.
3. Aplica IFFT para formar la senal OFDM en tiempo.

Los pilotos no son datos de la imagen. Son referencias conocidas que ayudan al
receptor a estimar el canal.

## Recepcion

En recepcion ocurre lo contrario:

1. Se retira el prefijo ciclico.
2. Se aplica FFT.
3. Se recuperan las subportadoras activas.
4. Se extraen los pilotos recibidos.
5. Se estima el canal.
6. Se ecualizan los datos.

La funcion principal es:

```python
demodulate_ofdm_with_pilots(...)
```

## Estimacion basica con pilotos

Si `X_p` es el piloto transmitido y `Y_p` es el piloto recibido, entonces el
canal estimado en esa subportadora es:

```text
H_p = Y_p / X_p
```

Esto se conoce como estimacion LS en pilotos.

En el codigo aparece como:

```python
h_ls = active_grid[block_idx, pilot_mask] / pilots[block_idx]
```

## Que hace el programa despues

El programa no se queda solo con los valores de canal en pilotos. Tambien
reconstruye una respuesta de canal para todas las subportadoras activas.

Para eso usa una estimacion en dominio temporal:

1. Junta las observaciones de pilotos.
2. Calcula una version estimada de los taps del canal.
3. Aplica FFT a esos taps.
4. Obtiene `H[k]` para todas las subportadoras.

## Ecualizacion

Una vez estimado el canal, el receptor corrige cada subportadora con un
ecualizador MMSE escalar:

```text
X_estimado[k] = H_estimado*[k] Y[k] / (|H_estimado[k]|^2 + sigma^2)
```

En el codigo:

```python
equalized_grid = active_grid * np.conj(h_est) / (np.abs(h_est) ** 2 + noise_to_signal)
```

Si `noise_to_signal = 0`, esta formula se reduce al caso Zero-Forcing.

## Y el MMSE?

El programa usa dos ideas relacionadas con MMSE:

1. Una estimacion de canal regularizada:

```python
(A^H A + lambda I)^(-1) A^H
```

2. Una ecualizacion MMSE escalar que usa `noise_to_signal` calculado desde la
   SNR de simulacion.

Por eso, en este simulador:

- Estimacion inicial en pilotos: LS.
- Reconstruccion del canal: LS regularizado en dominio temporal.
- Ecualizacion final: MMSE escalar por subportadora.
- Relacion con MMSE: aparece en la regularizacion del canal y en la
  ecualizacion final.

## Resumen del flujo

```text
Datos + pilotos
      |
      v
IFFT + CP
      |
      v
Canal + ruido
      |
      v
Quitar CP + FFT
      |
      v
Comparar pilotos recibidos con pilotos conocidos
      |
      v
Estimar H[k]
      |
      v
Ecualizar datos: Y[k] / H[k]
```
