# MIMO en el simulador LTE-OFDM

Este documento conecta la teoria MIMO vista en clase con la version actual del
simulador. La implementacion esta pensada para presentar la practica 10 con una
cadena clara: modulacion digital, OFDM, canal Rayleigh MIMO, deteccion espacial
y medicion de BER.

## 1. Idea principal

MIMO significa usar multiples antenas en transmision y/o recepcion. En esta
practica interesa principalmente la multiplexacion espacial: transmitir mas de
un flujo de simbolos al mismo tiempo, en la misma banda, aprovechando que el
canal entre cada antena transmisora y receptora es distinto.

Para una subportadora OFDM, el modelo base es:

```text
y[k] = H[k] s[k] + n[k]
```

donde:

- `y[k]` es el vector recibido en las antenas RX.
- `H[k]` es la matriz de canal MIMO de esa subportadora.
- `s[k]` es el vector de capas transmitidas.
- `n[k]` es ruido AWGN.

En SISO, `H[k]` es un escalar. En MIMO, `H[k]` es una matriz y el receptor debe
separar capas que llegaron mezcladas.

## 2. Papel de OFDM

OFDM divide el canal de banda ancha en muchas subportadoras. Si el prefijo
ciclico cubre suficientemente la dispersion temporal del canal, cada
subportadora puede tratarse aproximadamente como un canal plano.

Eso permite convertir un problema dificil de convolucion en tiempo en muchos
problemas simples por subportadora:

```text
subportadora k -> y[k] = H[k] s[k] + n[k]
```

El simulador conserva esta parte esencial:

1. Agrupa simbolos QAM en subportadoras activas.
2. Aplica IFFT para generar la senal temporal.
3. Agrega prefijo ciclico.
4. Pasa por canal multipath Rayleigh y AWGN.
5. Retira el prefijo ciclico.
6. Aplica FFT.
7. Detecta los simbolos usando `H[k]`.

La version actual no reserva subportadoras para estimacion de canal. Todas las
subportadoras activas se usan como datos.

## 3. CSI directa

En LTE real, el receptor estima el canal usando senales de referencia. Para esta
practica se decidio simplificar esa parte y usar directamente el canal generado
por la simulacion.

Esto significa que el receptor tiene CSI directa:

```text
H[k] = FFT de los taps Rayleigh generados por el simulador
```

Esta decision reduce complejidad y deja el foco en lo que se quiere mostrar:

- Como se mezclan las capas espaciales.
- Como ZF, IRC/MMSE y MMSE-SIC separan esas capas.
- Como cambia la BER al variar antenas, rank, detector, modulacion y SNR.

No es una implementacion LTE completa de senales de referencia, pero es una
abstraccion valida para estudiar deteccion MIMO.

## 4. Capas, antenas y rank

El rank usado por el simulador coincide con el numero de capas espaciales
transmitidas. Una capa es un flujo independiente de simbolos QAM.

Ejemplo:

```text
SM 2x2 -> 2 TX, 2 RX, 2 capas, rank 2
SM 4x2 -> 4 TX, 2 RX, 2 capas, rank 2
SM 4x4 rank 2 -> 4 TX, 4 RX, 2 capas, rank 2
SM 4x4 rank maximo -> 4 TX, 4 RX, 4 capas, rank 4
```

El rank no es simplemente "cuantas antenas hay". Es cuantos flujos
independientes se intentan transmitir simultaneamente. Para que el receptor los
separe bien, la matriz efectiva del canal debe tener suficiente rango y estar
bien condicionada.

## 5. Modos implementados

| Modo | TX fisicas | RX fisicas | Capas | Factor ideal |
| --- | ---: | ---: | ---: | ---: |
| `SISO 1x1` | 1 | 1 | 1 | `1x` |
| `SM 2x2` | 2 | 2 | 2 | `2x` |
| `SM 4x2` | 4 | 2 | 2 | `2x` |
| `SM 4x4 R2` | 4 | 4 | 2 | `2x` |
| `SM 4x4` | 4 | 4 | 4 | `4x` |

El factor ideal indica cuantos simbolos QAM se transmiten por subportadora
activa. No incluye codificacion de canal, scheduling, HARQ ni senalizacion LTE.

## 6. Caso 4x2 con precoding fijo

`SM 4x2` tiene 4 antenas transmisoras, 2 antenas receptoras y 2 capas. No se
transmiten 4 capas porque solo hay 2 antenas RX; intentar separar 4 flujos con
2 observaciones seria un sistema subdeterminado.

Por eso el simulador usa un precoder fijo:

```text
W = 1/sqrt(2) * [[1, 0],
                 [0, 1],
                 [1, 0],
                 [0, 1]]
```

El canal fisico es:

```text
H fisico: 2 x 4
```

Pero el receptor detecta sobre el canal efectivo:

```text
H_eff = H fisico @ W
H_eff: 2 x 2
```

Asi, 4x2 se presenta como una extension con diversidad/precoding en
transmision, pero mantiene 2 capas detectables.

## 7. Detectores

### ZF

Zero Forcing busca invertir la mezcla espacial:

```text
s_hat = pinv(H) y
```

Si el canal esta bien condicionado, separa bien las capas. Si el canal esta mal
condicionado, puede amplificar mucho el ruido.

### IRC/MMSE

En la interfaz se etiqueta como `IRC/MMSE` porque conceptualmente representa una
version regularizada frente a ruido e interferencia. Internamente se usa el
detector MMSE lineal:

```text
s_hat = (H^H H + sigma2 I)^-1 H^H y
```

Suele ser mas estable que ZF, especialmente a SNR media o baja.

### MMSE-SIC

SIC significa Successive Interference Cancellation. El receptor:

1. Detecta una capa.
2. La cuantiza al punto QAM mas cercano.
3. Resta su contribucion de la senal recibida.
4. Repite el proceso con las capas restantes.

Puede mejorar respecto al detector lineal cuando las primeras decisiones son
correctas. Si se equivoca temprano, el error puede propagarse.

## 8. Escalamiento de potencia

Para comparar de forma justa, la potencia total transmitida se mantiene
comparable entre modos. El simulador escala la senal transmitida por:

```text
1 / sqrt(numero_de_capas)
```

Asi, pasar de 2 capas a 4 capas no multiplica artificialmente la potencia total.
El aumento de throughput viene de transmitir mas flujos, no de transmitir con
mas energia.

## 9. Imagen y curvas BER

La imagen se usa para visualizar el efecto final de la cadena:

```text
imagen -> bits -> QAM -> OFDM MIMO -> canal -> detector -> bits -> imagen
```

Esto es ideal para presentar resultados al docente porque se ve si la
reconstruccion mejora o empeora.

Las curvas BER, en cambio, usan bits aleatorios reproducibles. Esto es mas
limpio para comparar modulaciones y modos MIMO porque:

- No depende del contenido especifico de la imagen.
- Permite usar la misma cantidad de bits para todos los casos.
- Mide directamente el comportamiento estadistico del enlace.

En resumen:

```text
PRUEBA MULTIANTENA -> evidencia visual con la imagen seleccionada
CURVAS BER -> Monte Carlo con bits aleatorios
Rank 2 -> compara 2 capas en 2x2, 4x2 y 4x4
Rank maximo -> deja que 4x4 use 4 capas
```

## 10. Resultados esperables

Al aumentar la SNR, la BER deberia bajar.

Al aumentar el orden de modulacion, la BER suele subir para la misma SNR:

```text
QPSK suele ser mas robusta que 16-QAM
16-QAM suele ser mas robusta que 64-QAM
```

IRC/MMSE normalmente deberia comportarse mejor que ZF cuando el ruido importa.
SIC puede mejorar algunos casos, pero no siempre domina porque depende de que
las decisiones sucesivas sean confiables.

`SM 4x4` con rank maximo puede transportar mas capas que `SM 2x2`, pero no
necesariamente tendra menor BER. Con 4 capas hay mas flujos simultaneos que
separar, la potencia se reparte entre mas capas y el rendimiento depende mucho
de la condicion de `H[k]`. Por eso el modo `Rank 2` es la comparacion mas justa
cuando se quiere aislar el efecto del arreglo de antenas sin cambiar el numero
de capas.

`SM 4x2` no duplica el rank respecto a `2x2`; mantiene 2 capas. Su interes esta
en mostrar 4 antenas TX con precoding fijo y un canal efectivo `2x2`.

## 11. Como explicar la practica

Una forma breve de defender la implementacion es:

> El simulador implementa multiplexacion espacial SU-MIMO sobre OFDM. La imagen
> se divide en capas espaciales y se transmite simultaneamente por multiples
> antenas. Para concentrar la practica en deteccion MIMO, el receptor usa la
> matriz de canal generada por el simulador como CSI directa. Luego recupera las
> capas con ZF, IRC/MMSE o MMSE-SIC. La imagen permite validar visualmente la
> reconstruccion, mientras que las curvas BER usan bits aleatorios para comparar
> de forma estadistica los arreglos 2x2, 4x2 y 4x4.

## 12. Limites del modelo

- No implementa LTE completo.
- No modela estimacion real de canal.
- No implementa CRS, DM-RS, PMI, codebooks, HARQ ni codificacion de canal.
- El canal es estatico durante cada corrida.
- `IRC/MMSE` es una aproximacion didactica basada en MMSE, no un receptor IRC
  LTE completo con matriz general de covarianza de interferencia.
- `4x2` usa un precoder fijo, no adaptacion dinamica de rank o PMI.
