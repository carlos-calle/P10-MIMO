# Calculo de PAPR en el simulador

Este documento explica como se calcula la curva PAPR/CCDF en el simulador LTE-OFDM y que significa el resultado que aparece en la pestana "Analisis PAPR".

## Que es PAPR

PAPR significa `Peak-to-Average Power Ratio`. En una senal OFDM mide que tan grande es el pico instantaneo de potencia respecto a la potencia media del mismo simbolo.

Para un simbolo OFDM discreto `x[n]`, el PAPR lineal es:

```text
PAPR = max(|x[n]|^2) / mean(|x[n]|^2)
```

En decibelios:

```text
PAPR_dB = 10 * log10(PAPR)
```

OFDM suele tener PAPR alto porque muchas subportadoras pueden sumarse constructivamente en algunos instantes. Esto es importante en sistemas reales porque obliga al amplificador de potencia a operar con back-off; si no, los picos se recortan y aparecen distorsion e interferencia fuera de banda.

## Como lo calcula este proyecto

El calculo esta en `controller/simulation_mgr.py`, dentro de `calculate_papr_distribution`.

El flujo actual es:

1. Se carga la imagen seleccionada y se convierte a bits.
2. Se aplica scrambling a esos bits.
3. Los bits se mapean por separado a QPSK, 16-QAM y 64-QAM.
4. Los simbolos complejos se agrupan en bloques OFDM dejando espacio para pilotos.
5. Se insertan pilotos QPSK deterministas cada 6 subportadoras activas.
6. Para calcular PAPR se genera una version sobremuestreada del simbolo OFDM.
7. Se calcula la potencia instantanea `|x[n]|^2`.
8. Por cada bloque OFDM se calcula:

```text
PAPR_dB = 10 * log10(max(power) / mean(power))
```

9. Con todos los PAPR obtenidos se estima la CCDF:

```text
CCDF(gamma) = P(PAPR > gamma)
```

Es decir, para cada umbral en dB se cuenta que fraccion de bloques OFDM superan ese umbral.

Los pilotos no son un simbolo constante repetido. El transmisor y el receptor
usan la misma secuencia QPSK deterministica, con potencia unitaria. Esto evita
que los pilotos formen una peineta de fase fija que infle artificialmente el
PAPR, pero conserva la idea de pilotos conocidos para estimacion de canal.

## Por que se usa sobremuestreo

Medir el PAPR solo con las muestras de una IFFT de tamano `N_FFT` puede subestimar los picos reales de la senal continua. Algunos picos pueden aparecer entre muestras.

Por eso el simulador usa un factor de sobremuestreo `L = 4` para PAPR:

```text
N_FFT_PAPR = L * N_FFT
```

Las mismas subportadoras activas se insertan alrededor de DC en una FFT mas grande, se hace la IFFT, y luego se calcula el PAPR con mas muestras temporales. Esto da una estimacion mas realista del PAPR de la forma de onda OFDM.

## Por que ya no se usa Monte Carlo para PAPR

No es estrictamente necesario.

Para el objetivo actual del simulador queremos el PAPR empirico de la imagen cargada. En ese caso basta con:

1. tomar la imagen,
2. generar una unica secuencia OFDM,
3. calcular el PAPR de todos sus bloques,
4. construir la CCDF con esos bloques.

Eso ya es un resultado valido para esa realizacion concreta y permite comparar directamente QPSK, 16-QAM y 64-QAM.

Tambien es posible usar Monte Carlo para PAPR si se quiere estimar una CCDF estadistica bajo muchas realizaciones de datos. En ese caso no cambiaria la carga util conceptual, porque se podria seguir partiendo de la misma imagen y variar el scrambling. Pero esa decision suaviza la curva y la vuelve una estimacion estadistica, no la CCDF de una corrida concreta.

Por pedido actual, el simulador elimina Monte Carlo en PAPR y hace esto:

- una sola realizacion OFDM por modulacion;
- misma imagen de entrada;
- mismo ancho de banda y prefijo ciclico seleccionados;
- comparacion simultanea de QPSK, 16-QAM y 64-QAM;
- sin intervalo de confianza, porque no hay corridas Monte Carlo.

La diferencia conceptual es esta:

```text
PAPR de una corrida:
    CCDF empirica de una secuencia OFDM concreta de la imagen.

PAPR comparativo actual:
    Tres CCDF empiricas, una para QPSK, una para 16-QAM y una para 64-QAM.
```

## Que no afecta al PAPR

El PAPR se calcula en transmision, antes del canal. Por eso no depende de:

- SNR;
- ruido AWGN;
- canal Rayleigh;
- ecualizacion;
- BER.

PAPR depende principalmente de:

- cantidad de subportadoras activas;
- modulacion;
- datos transmitidos;
- patron de pilotos;
- forma de mapear subportadoras;
- sobremuestreo usado para medir picos.

## Prefijo ciclico

El calculo actual mide PAPR sobre el simbolo OFDM util, antes de insertar prefijo ciclico.

Esto es una practica razonable para analizar el simbolo OFDM base. El prefijo ciclico es una copia del final del simbolo; no crea muestras nuevas, pero si se incluyera en la medicion podria cambiar levemente la potencia media de una ventana concreta porque duplica una parte del simbolo.

Para comparar modulaciones o configuraciones OFDM, medir antes del CP es limpio y consistente.

## Como leer la grafica

El eje X es el umbral de PAPR en dB.

El rango del eje se ajusta al PAPR maximo observado en la imagen cargada para
evitar truncar la cola de la CCDF.

El eje Y es:

```text
P(PAPR > umbral)
```

Ejemplo:

```text
CCDF(9 dB) = 0.25
```

significa que aproximadamente el 25% de los bloques OFDM tuvieron PAPR mayor que 9 dB.

La grafica actual no muestra banda de confianza para PAPR porque ya no se ejecuta Monte Carlo.

El resumen mostrado debajo de la grafica indica:

- el ancho de banda seleccionado y sus subportadoras activas;
- el numero de bloques OFDM evaluados para QPSK, 16-QAM y 64-QAM;
- el factor de sobremuestreo `L=4`;
- `CP/canal: no aplican`, porque el calculo ocurre antes de insertar prefijo
  ciclico y antes de pasar por el canal Rayleigh.

## Limitaciones

- Es una estimacion discreta de PAPR, aunque mejorada con sobremuestreo.
- No modela filtros de transmision, DAC, clipping ni no linealidad del amplificador.
- No incluye asignacion LTE completa de resource elements, pilotos o canales fisicos.
- La CCDF depende de la imagen y del scrambling deterministico usado para generar la secuencia OFDM.

En resumen: el calculo actual es correcto para un simulador OFDM baseband educativo. No reemplaza una simulacion RF completa, pero si representa bien el problema central de PAPR en OFDM.
