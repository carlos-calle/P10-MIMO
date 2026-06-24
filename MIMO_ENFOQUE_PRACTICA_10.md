# Enfoque especifico de la practica 10 MIMO

Este documento resume que esta haciendo especificamente nuestro simulador para
la practica 10, como se relaciona con la teoria vista en clase y que decisiones
se tomaron para mantener la implementacion clara, defendible y enfocada en
MIMO.

## 1. Objetivo de la practica

El objetivo no es construir una pila LTE completa, sino mostrar el efecto de la
multiplexacion espacial MIMO sobre una cadena LTE-OFDM educativa.

La idea central es:

```text
una fuente de bits -> modulacion QAM -> capas espaciales -> canal MIMO
-> detector espacial -> bits reconstruidos -> BER / imagen reconstruida
```

La practica se concentra en responder estas preguntas:

- Que ocurre cuando transmitimos mas de una capa espacial al mismo tiempo.
- Como cambia la BER al usar `2x2`, `4x2` o `4x4`.
- Como se comparan los detectores `IRC/MMSE` y `MMSE-SIC`.
- Como influye el rank en una comparacion justa.
- Que diferencia visual se observa al reconstruir una imagen.

## 2. Que tipo de MIMO estamos simulando

El simulador usa SU-MIMO con multiplexacion espacial. Esto significa que hay una
sola fuente de informacion, pero sus simbolos se reparten en varias capas
espaciales.

No estamos simulando varios usuarios independientes. Tampoco estamos haciendo
beamforming como objetivo principal. El foco es la separacion de capas MIMO en el
receptor.

Para una subportadora OFDM, el modelo es:

```text
y[k] = H[k] s[k] + n[k]
```

donde:

- `s[k]` contiene las capas transmitidas.
- `H[k]` es el canal MIMO.
- `y[k]` es lo observado por las antenas receptoras.
- `n[k]` es el ruido.

El receptor debe estimar las capas originales a partir de una mezcla espacial.

## 3. Modos multiantena usados

La comparacion principal usa seis escenarios:

```text
2x2 R2 IRC/MMSE
4x2 R2 IRC/MMSE
4x4 R2 o R4 IRC/MMSE
2x2 R2 SIC
4x2 R2 SIC
4x4 R2 o R4 SIC
```

La diferencia entre `R2` y `R4` es el rank, es decir, el numero de capas
espaciales transmitidas simultaneamente.

| Caso | TX | RX | Capas | Comentario |
| --- | ---: | ---: | ---: | --- |
| `2x2 R2` | 2 | 2 | 2 | Caso base de multiplexacion espacial. |
| `4x2 R2` | 4 | 2 | 2 | Usa 4 antenas TX, pero solo 2 capas detectables. |
| `4x4 R2` | 4 | 4 | 2 | Comparacion justa contra 2 capas. |
| `4x4 R4` | 4 | 4 | 4 | Extension de mayor rank y mayor exigencia. |

Esto permite presentar dos lecturas:

- `Rank 2`: comparacion mas justa, porque todos transmiten dos capas.
- `Rank maximo`: muestra que `4x4` puede transmitir cuatro capas, pero tambien
  que esa ganancia exige un canal mejor condicionado y mayor SNR.

## 4. Por que 4x2 no transmite cuatro capas

En `4x2` hay 4 antenas transmisoras, pero solo 2 antenas receptoras. Si se
intentaran transmitir 4 capas independientes, el receptor tendria 2 observaciones
para separar 4 incognitas. Ese problema queda subdeterminado.

Por eso nuestro `4x2` usa 2 capas y un precoder fijo:

```text
W = 1/sqrt(2) * [[1, 0],
                 [0, 1],
                 [1, 0],
                 [0, 1]]
```

El canal fisico es:

```text
H: 2 x 4
```

pero el receptor trabaja sobre el canal efectivo:

```text
H_eff = H @ W
H_eff: 2 x 2
```

Asi, `4x2` aprovecha mas antenas transmisoras, pero mantiene dos capas
separables.

## 5. Como usamos la modulacion

En cada corrida se escoge una sola modulacion:

```text
QPSK, 16-QAM o 64-QAM
```

Esa modulacion se aplica a todos los simbolos de la prueba. Luego los simbolos
QAM resultantes se reparten entre capas espaciales.

Esto es importante: no transmitimos la misma informacion simultaneamente en
QPSK, 16-QAM y 64-QAM para que el receptor vaya restando modulaciones. Esa idea
se parece mas a superposicion de potencia o NOMA, no a la explicacion MIMO-SIC
que estamos usando.

En nuestro caso:

```text
bits -> una modulacion activa -> simbolos QAM -> capas MIMO
```

## 6. Como interpretamos SIC

SIC significa Successive Interference Cancellation. En el material de clase se
presenta como un procesamiento no lineal en recepcion para senales
multiplexadas espacialmente.

La idea es:

1. Detectar una capa.
2. Decidir a que simbolo QAM corresponde.
3. Reconstruir la contribucion de esa capa en la senal recibida.
4. Restarla.
5. Repetir el proceso con las capas restantes.

En forma simplificada:

```text
y = H1*s1 + H2*s2 + ruido

1) detectar s1
2) reconstruir H1*s1
3) y_restante = y - H1*s1
4) detectar s2 con menos interferencia
```

El curso menciona que SIC se asocia a senales codificadas separadamente antes de
la multiplexacion espacial. En LTE real eso puede implicar multi-codeword,
codificacion de canal, CRC y decodificacion por codeword.

Nuestro simulador no implementa toda esa pila. Hace una aproximacion didactica a
nivel de capas y simbolos QAM:

```text
capa detectada -> decision QAM -> cancelacion espacial -> siguiente capa
```

Por eso es correcto presentarlo como `MMSE-SIC simplificado a nivel de capas`,
no como un receptor LTE completo.

## 7. IRC/MMSE en nuestro simulador

En la interfaz usamos la etiqueta `IRC/MMSE` porque en clase se habla de
receptores que combinan las antenas para reducir interferencia entre capas.

Internamente usamos el detector MMSE lineal:

```text
s_hat = (H^H H + sigma2 I)^-1 H^H y
```

Este detector no fuerza una inversion exacta del canal como ZF. Regulariza la
inversion usando el nivel de ruido, por lo que suele ser mas estable cuando el
canal esta mal condicionado o la SNR no es alta.

Es una aproximacion didactica a IRC, no un IRC LTE completo con matriz general de
covarianza de interferencia.

## 8. Por que quitamos pilotos y estimacion explicita

En practicas anteriores, las subportadoras piloto eran importantes para estudiar
OFDM y estimacion de canal.

En esta practica se decidio simplificar esa parte:

```text
el receptor usa directamente el canal generado por el simulador
```

Eso equivale a asumir CSI conocida. La ventaja es que la practica queda centrada
en MIMO:

- Separacion de capas.
- Rank.
- Precoding fijo.
- Detectores IRC/MMSE y SIC.
- Curvas BER.
- Comparacion visual.

No se pretende demostrar una implementacion completa de las senales de
referencia LTE.

## 9. Por que las curvas BER usan bits aleatorios

La imagen es util para una demostracion visual, especialmente con `cameraman`.
Permite ver inmediatamente si la reconstruccion es buena o mala.

Sin embargo, para curvas BER conviene usar bits aleatorios reproducibles:

- La comparacion no depende del contenido de una imagen.
- Todos los escenarios reciben una carga util equivalente.
- El resultado representa mejor el comportamiento estadistico del enlace.
- Es mas rapido y limpio para barrer varios puntos de SNR.

Por eso la interfaz separa:

```text
PRUEBA MULTIANTENA -> usa la imagen seleccionada
CURVAS BER         -> usa bits aleatorios
```

Ambas pruebas usan la modulacion seleccionada por el usuario.

## 10. Que esperamos observar

Al aumentar la SNR, la BER deberia disminuir.

Con modulaciones mas densas, la BER suele empeorar para la misma SNR:

```text
QPSK suele ser mas robusta que 16-QAM
16-QAM suele ser mas robusta que 64-QAM
```

En `Rank 2`, la comparacion entre `2x2`, `4x2` y `4x4` es mas justa, porque
todos transmiten dos capas. En ese caso, `4x4 R2` puede beneficiarse de mas
observaciones RX para separar las capas.

En `Rank maximo`, `4x4 R4` transmite cuatro capas. Eso aumenta el numero ideal
de simbolos enviados por subportadora, pero tambien hace mas dificil la
deteccion. Por eso puede verse peor en BER que `2x2 R2` o `4x2 R2`, sobre todo a
SNR baja o media.

Esto no significa que `4x4` sea "malo". Significa que se esta usando para
transmitir mas flujos simultaneos, y esa comparacion ya no es BER contra BER con
la misma carga espacial.

## 11. Relacion con los trabajos de referencia

### MontanoPortilla

Su trabajo es el mas cercano a nuestra direccion. Compara configuraciones
multiantena, rank, precoding y detectores como MMSE/IRC, ZF y SIC.

Nosotros tomamos esa idea general, pero la dejamos mas controlada:

- Rank fijo seleccionable: `Rank 2` o `Rank maximo`.
- Precoder fijo para `4x2`.
- Comparacion directa de seis escenarios.
- Sin PMI dinamico ni rank adaptation completa.

### Andres

Su notebook trabaja con modulaciones QPSK, 16-QAM y 64-QAM, pero usa una
modulacion activa por corrida. Tambien incluye una logica de remodulacion y
cancelacion que se parece al principio de SIC.

Nuestra implementacion conserva esa idea conceptual de reconstruir y cancelar,
pero la integra de forma mas directa en el detector MIMO por capa.

### Mateo

Su enfoque va mas hacia MU-MIMO/beamforming, con usuarios y configuraciones
independientes. Puede usar distintas modulaciones por usuario, pero eso no es lo
mismo que SIC por capas espaciales de una sola fuente.

Nuestro simulador se mantiene en SU-MIMO, que es mas coherente con la practica
actual y con la comparacion por rank.

## 12. Que no estamos implementando

Para evitar confusiones en la presentacion, conviene decir explicitamente que no
se implementa:

- MU-MIMO multiusuario.
- NOMA o superposicion de QPSK/16-QAM/64-QAM al mismo tiempo.
- SIC LTE completo con CRC y decodificacion real de codewords.
- Rank adaptation dinamica.
- PMI/codebook LTE completo.
- HARQ, scheduling o capas superiores LTE.
- Estimacion de canal con pilotos CRS.
- PAPR, porque ya no forma parte del objetivo de la practica.

Estas omisiones son decisiones de alcance. La practica se enfoca en observar el
comportamiento MIMO de forma clara.

## 13. Forma recomendada de explicarlo

Una forma corta y defendible de presentar el simulador seria:

```text
Implementamos una cadena LTE-OFDM simplificada para estudiar multiplexacion
espacial SU-MIMO. La informacion de una imagen o de bits aleatorios se modula
con QPSK, 16-QAM o 64-QAM y se reparte en capas espaciales segun el rank. El
canal MIMO mezcla esas capas y el receptor las separa con IRC/MMSE o con
MMSE-SIC. Para comparar de forma justa, la interfaz permite usar Rank 2 en todos
los arreglos, o Rank maximo para mostrar la extension 4x4 completa.
```

Y si preguntan por SIC:

```text
Nuestro SIC no mezcla distintas modulaciones. Usa una sola modulacion activa y
cancela sucesivamente la interferencia entre capas espaciales. Es una version
didactica a nivel de simbolos QAM, alineada con la idea de SIC del material, pero
sin implementar la pila LTE completa de multi-codeword y codificacion de canal.
```

