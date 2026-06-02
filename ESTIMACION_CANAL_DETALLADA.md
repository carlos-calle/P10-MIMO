# Estimacion De Canal En El Simulador LTE-OFDM

Este documento explica, de forma didactica y paso a paso, como se realiza la estimacion de canal dentro de este simulador. La idea no es solo describir que hace el programa, sino tambien por que se hace asi, que problema resuelve cada bloque y como se conectan entre si la modulacion OFDM, los pilotos, el prefijo ciclico y la ecualizacion.

El flujo principal se coordina desde [controller/simulation_mgr.py](controller/simulation_mgr.py), mientras que la parte matematica de OFDM y la estimacion de canal viven en [core/ofdm_ops.py](core/ofdm_ops.py). El modelo fisico del canal multipath esta en [core/channel.py](core/channel.py).

## 1. Idea General

En un sistema OFDM, cada subportadora ve al canal como una ganancia compleja distinta. Si el canal fuera conocido en recepcion, bastaria dividir la señal recibida por esa ganancia para recuperar los simbolos enviados. El problema real es que el receptor no conoce el canal a priori.

Por eso se insertan **pilotos**: simbolos conocidos tanto por transmisor como por receptor. Al comparar lo que se envio con lo que llega, el receptor obtiene una medida de la respuesta del canal en esas subportadoras. Luego usa esa informacion para construir una estimacion completa de $H[k]$ y ecualizar los datos.

En este proyecto se usan dos ideas complementarias:

1. **Estimacion en frecuencia desde pilotos**: se calcula una estimacion LS en las subportadoras piloto y luego se interpola entre ellas.
2. **Estimacion en dominio temporal con regularizacion ridge**: cuando se conoce o se acota el numero de taps del canal, la estimacion se lleva al dominio del tiempo y luego se reconstruye la respuesta en frecuencia.

## 2. Dónde Ocurre Cada Cosa

La cadena completa de transmision y recepcion se ejecuta en [controller/simulation_mgr.py](controller/simulation_mgr.py), especialmente en `run_image_transmission`.

Las funciones mas importantes son:

- `modulate_ofdm_with_pilots(...)` en [core/ofdm_ops.py](core/ofdm_ops.py)
- `add_cyclic_prefix(...)` en [core/ofdm_ops.py](core/ofdm_ops.py)
- `apply_rayleigh(...)` en [core/channel.py](core/channel.py)
- `remove_cyclic_prefix(...)` en [core/ofdm_ops.py](core/ofdm_ops.py)
- `demodulate_ofdm_with_pilots(...)` en [core/ofdm_ops.py](core/ofdm_ops.py)

En pocas palabras:

1. Se convierten bits a simbolos complejos.
2. Se insertan pilotos conocidos en las subportadoras activas.
3. Se pasa a dominio temporal con IFFT.
4. Se agrega prefijo ciclico.
5. La señal atraviesa un canal Rayleigh multipath y ruido AWGN.
6. Se elimina el CP.
7. Se vuelve al dominio de la frecuencia con FFT.
8. Se estiman las subportadoras del canal usando los pilotos.
9. Se ecualiza la señal.
10. Se recuperan bits e imagen.

## 3. Por Que El Prefijo Ciclico Importa

El prefijo ciclico no es un detalle estetico: evita que la convolucion lineal del canal multipath se convierta en interferencia entre simbolos OFDM, siempre que la duracion del CP sea suficiente para cubrir el retardo maximo del canal.

En este simulador esto se estudia con perfiles de canal como `Didactico CP` en [core/channel.py](core/channel.py), diseñado para que el retardo del eco secundario quede:

- fuera del CP normal, y
- dentro del CP extendido.

Eso permite observar claramente el efecto del CP sobre la calidad de la recepcion.

La funcion `cp_safety_report(...)` compara el retardo maximo del canal con la longitud minima del CP y devuelve si se espera o no ISI.

## 4. Construccion Del Canal

### 4.1 Modelo Rayleigh multipath

El canal se genera en [core/channel.py](core/channel.py) con `generate_rayleigh_channel(...)`.

Si no se entrega `sample_rate_hz`, se usa un modelo Rayleigh exponencial simple. Si si se entrega, el canal se discretiza a partir de un perfil de retardos y ganancias, por ejemplo:

- ITU Pedestrian A
- ITU Pedestrian B
- ITU Vehicular A
- ITU Vehicular B
- Didactico CP

El simulador convierte los retardos en segundos a retardos en muestras y crea una respuesta impulsiva discreta $h[n]$.

### 4.2 Aplicacion del canal

La funcion `apply_rayleigh(...)` hace dos cosas:

1. Convoluciona la señal transmitida con $h[n]$.
2. Agrega ruido AWGN segun la SNR indicada.

Eso produce la señal recibida realista que luego entra al receptor OFDM.

## 5. Insercion De Pilotos

La estimacion de canal depende por completo de los pilotos. Aqui el proyecto usa un patron muy concreto y reproducible.

### 5.1 Pilotos deterministas

La funcion `pilot_symbol_grid(...)` genera simbolos QPSK conocidos por transmisor y receptor. No son aleatorios en cada ejecucion: se usan siempre los mismos valores para que la estimacion sea reproducible.

Eso es importante porque el receptor no necesita adivinar cuales fueron los pilotos: ya los conoce por diseno.

### 5.2 Mascara de pilotos

La funcion `pilot_subcarrier_mask(...)` marca cada cuantas subportadoras activas se coloca un piloto. Por defecto el espaciamiento es de 6 subportadoras activas.

La variante `pilot_subcarrier_masks(...)` construye una mascara por bloque OFDM.

### 5.3 Desplazamiento escalonado

El proyecto no usa siempre el mismo patron de pilotos en todos los bloques. En cambio, alterna un desplazamiento entre bloques con `PILOT_STAGGER_ENABLED`.

La idea es simple:

- bloque par: pilotos en una posicion,
- bloque impar: pilotos corridos media separacion.

Con eso se densifica la informacion de canal en frecuencia sin aumentar demasiado el overhead.

## 6. Modelo Matematico De La Estimacion

### 6.1 Observacion en piloto

En una subportadora piloto $k$, si se envio un valor conocido $X[k]$ y se recibio $Y[k]$, la estimacion LS basica es:

$$
\hat{H}[k] = \frac{Y[k]}{X[k]}
$$

Esto aparece de forma directa en la logica interna de `demodulate_ofdm_with_pilots(...)`.

### 6.2 Interpolacion en frecuencia

La estimacion solo existe en las posiciones de los pilotos. Para obtener un canal completo en todas las subportadoras activas, el simulador interpola linealmente la parte real e imaginaria de $\hat{H}[k]$.

Eso lo hacen:

- `_interpolate_channel_from_points(...)`
- `_interpolate_channel_from_pilots(...)`

La interpolacion separa real e imaginaria porque asi se mantiene una implementacion simple y estable, suficiente para el proposito educativo del simulador.

## 7. Dos Estrategias De Estimacion En Este Proyecto

La funcion central es `demodulate_ofdm_with_pilots(...)` en [core/ofdm_ops.py](core/ofdm_ops.py). Esa funcion elige entre tres caminos.

### 7.1 Camino A: estimacion con promedio temporal y LS en dominio temporal

Si `temporal_average=True` y se entrega `max_channel_taps`, el sistema usa `_estimate_channel_from_time_domain_ls(...)`.

El procedimiento es:

1. Se obtienen las observaciones LS en los pilotos.
2. Se estima un numero limitado de taps del canal en el dominio del tiempo.
3. Se regulariza la inversion con ridge para evitar inestabilidad numerica.
4. Se reconstruye la respuesta en frecuencia mediante FFT.
5. Se replica la estimacion para todos los bloques.

La parte clave es la regularizacion:

$$
\hat{\mathbf{h}} = (\mathbf{A}^H\mathbf{A} + \lambda \mathbf{I})^{-1} \mathbf{A}^H \mathbf{y}
$$

Aqui:

- $\mathbf{A}$ es la matriz construida con las exponenciales complejas del modelo de taps,
- $\mathbf{y}$ son las observaciones LS en pilotos,
- $\lambda$ es `channel_estimation_ridge`.

Esta rama es la mas interesante para analizar el efecto del CP, porque trata de reconstruir el canal desde una estructura temporal corta.

### 7.2 Camino B: promedio por bloques con patron escalonado

Si `temporal_average=True` pero no se conoce `max_channel_taps`, se usa `_estimate_channel_from_staggered_pilots(...)`.

En este caso:

1. Se promedian las observaciones LS de los pilotos que caen en cada subportadora.
2. Se interpola un canal medio mas denso.
3. Se aplica esa estimacion a todos los bloques.

Este enfoque explota el hecho de que los bloques alternan el patron de pilotos. Asi, entre bloques se cubren mas posiciones de frecuencia y la malla efectiva de observacion mejora.

### 7.3 Camino C: estimacion por bloque sin promedio temporal

Si `temporal_average=False`, cada bloque se estima por separado:

1. Se divide la recepcion en pilotos entre los pilotos conocidos.
2. Se interpola cada bloque independientemente.
3. No se promedia informacion entre bloques.

Es la opcion mas directa, pero tambien la mas sensible al ruido y a la variabilidad del canal.

## 8. Ecualizacion

Una vez que se tiene $\hat{H}[k]$, el receptor ecualiza por division compleja:

$$
\hat{X}[k] = \frac{Y[k]}{\hat{H}[k]}
$$

En el codigo eso ocurre dentro de `demodulate_ofdm_with_pilots(...)`, y tambien existe `equalize_channel(...)` como ecualizador Zero-Forcing para el caso en que ya se tenga la respuesta impulsiva del canal.

Para evitar divisiones numericamente inestables, el codigo aplica un umbral `threshold` y reemplaza valores demasiado pequenos por un minimo seguro.

## 9. Flujo Exacto En La Transmision De Imagen

La ruta completa de una imagen por el sistema es esta:

1. `image_to_bits(...)` transforma la imagen en bits.
2. `apply_scrambling(...)` mezcla los bits con una semilla fija o reproducible.
3. `map_bits_to_symbols(...)` crea simbolos QPSK, 16-QAM o 64-QAM.
4. `modulate_ofdm_with_pilots(...)` organiza los simbolos en subportadoras y agrega pilotos.
5. `add_cyclic_prefix(...)` protege cada bloque OFDM.
6. `apply_rayleigh(...)` modela el canal multipath + AWGN.
7. `remove_cyclic_prefix(...)` elimina el CP recibido.
8. `demodulate_ofdm_with_pilots(...)` recupera datos y estima el canal.
9. `demap_symbols_to_bits(...)` vuelve de simbolos a bits.
10. `apply_scrambling(...)` revierte el scrambling.
11. `bits_to_image(...)` reconstruye la imagen.

Todo esto se encapsula en `run_image_transmission(...)` en [controller/simulation_mgr.py](controller/simulation_mgr.py).

## 10. Por Que La Estimacion Es Reproducible

Hay dos semillas importantes:

- `mc_seed`: para barridos Monte Carlo.
- `image_tx_seed`: para la transmision manual de imagen.

Eso significa que repetir la misma configuracion produce la misma realizacion de canal y ruido, lo cual es muy util para depurar y comparar resultados.

## 11. Relacion Con La GUI

La interfaz no solo lanza la simulacion. Tambien muestra informacion que ayuda a entender la estimacion:

- numero de subportadoras activas,
- numero de bloques OFDM,
- tipo de CP,
- perfil del canal,
- numero de caminos,
- si el canal esperado cabe o no dentro del CP.

En otras palabras, la GUI no es solo una capa visual: expone variables que afectan directamente la calidad de la estimacion.

## 12. Que Se Aprende Con Este Montaje

Este simulador esta pensado para que se vea una cadena de ideas muy concreta:

1. El canal multipath distorsiona amplitud y fase por subportadora.
2. El CP evita ISI si cubre el retardo maximo.
3. Los pilotos permiten observar el canal en puntos conocidos.
4. La interpolacion reconstruye una estimacion continua en frecuencia.
5. La regularizacion ridge estabiliza la estimacion cuando se pasa al dominio temporal.
6. La ecualizacion corrige la distorsion antes de demodular.

## 13. Lectura Guiada Del Codigo

Si quieres seguir el proceso directamente en el codigo, este es el orden mas util de lectura:

1. [controller/simulation_mgr.py](controller/simulation_mgr.py) -> `run_image_transmission(...)`
2. [core/ofdm_ops.py](core/ofdm_ops.py) -> `modulate_ofdm_with_pilots(...)`
3. [core/ofdm_ops.py](core/ofdm_ops.py) -> `demodulate_ofdm_with_pilots(...)`
4. [core/ofdm_ops.py](core/ofdm_ops.py) -> `_estimate_channel_from_time_domain_ls(...)`
5. [core/channel.py](core/channel.py) -> `generate_rayleigh_channel(...)`
6. [core/channel.py](core/channel.py) -> `cp_safety_report(...)`

## 14. Resumen Corto

La estimacion de canal en este simulador no es una caja negra. Se construye a partir de pilotos OFDM conocidos, se refina con interpolacion o con una reconstruccion DFT/LS regularizada, y luego se usa para ecualizar las subportadoras recibidas. El canal multipath se modela de forma discreta y el CP permite estudiar de forma muy clara cuando la estimacion y la recepcion funcionan bien y cuando empiezan a aparecer problemas de ISI.

Si quieres, el siguiente paso natural es complementar este documento con diagramas de bloques o con un ejemplo numerico completo de una sola portadora piloto y una sola subportadora de datos.