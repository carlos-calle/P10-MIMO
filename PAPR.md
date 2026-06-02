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
5. Se insertan pilotos QPSK deterministas cada 6 subportadoras activas, con desplazamiento alternado entre bloques.
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

## Implementacion en codigo

El calculo se dispara desde la interfaz en `ui/main_window.py`, metodo
`action_plot_papr`. Cuando el usuario pulsa `ANALIZAR PAPR`, la GUI valida que
haya una imagen seleccionada, lee el ancho de banda y el prefijo ciclico, y
lanza un worker thread:

```python
self._start_worker(
    "papr",
    "Calculando PAPR de la imagen para 3 modulaciones...",
    self.manager.calculate_papr_distribution,
    (self.selected_image_path, bw_idx, prof_idx),
    self._show_papr_result,
)
```

El calculo numerico esta en `controller/simulation_mgr.py`. La clase
`OFDMSimulationManager` define:

```python
self.papr_oversampling = 4
```

Ese valor es el factor `L` de sobremuestreo usado despues para calcular una
IFFT mas grande.

### Funcion `calculate_papr_distribution`

Esta funcion coordina el analisis completo de PAPR:

```python
tx_bits_raw, _ = utils.image_to_bits(image_path, self.img_size)
series = [
    self._calculate_papr_series(tx_bits_raw, bw_idx, profile_idx, current_mod)
    for current_mod in (1, 2, 3)
]
```

Primero carga la imagen y la convierte a bits con `utils.image_to_bits`. Luego
calcula una serie por cada modulacion:

- `1`: QPSK.
- `2`: 16-QAM.
- `3`: 64-QAM.

Cada serie contiene los valores individuales de PAPR de todos los bloques OFDM
generados para esa modulacion.

Despues se obtiene el mayor PAPR observado:

```python
max_papr = max(float(np.max(item["papr_values"])) for item in series if item["total_blocks"] > 0)
```

Con ese maximo se construye el eje X de la grafica:

```python
thresholds = np.linspace(0, max(12, np.ceil(max_papr) + 1), 120)
```

Esto genera 120 umbrales entre 0 dB y un valor suficiente para cubrir la cola
de la CCDF. El limite inferior de 12 dB evita que la grafica quede demasiado
corta cuando los PAPR observados son menores.

Luego, para cada modulacion, se calcula la CCDF:

```python
exceed_counts = np.sum(papr_values[:, None] > thresholds[None, :], axis=0)
item["y"] = exceed_counts / len(papr_values)
```

La expresion `papr_values[:, None] > thresholds[None, :]` compara todos los
PAPR contra todos los umbrales. El resultado es una matriz booleana donde cada
fila representa un bloque OFDM y cada columna representa un umbral. Al sumar
por columnas se cuenta cuantos bloques superan cada umbral.

Finalmente la funcion devuelve un diccionario con:

- `x`: umbrales de PAPR en dB.
- `series`: curvas QPSK, 16-QAM y 64-QAM.
- `oversampling`: factor `L`.
- `blocks_by_modulation`: cantidad de bloques evaluados por modulacion.
- `config_summary`: resumen de ancho de banda y subportadoras activas.
- `summary`: texto mostrado debajo de la grafica.

### Funcion `_calculate_papr_series`

Esta funcion prepara los simbolos de una modulacion especifica:

```python
n_fft, nc, _, _ = utils.get_ofdm_params(bw_idx, profile_idx)
tx_bits = utils.apply_scrambling(tx_bits_raw, seed=self.mc_seed)
syms = utils.map_bits_to_symbols(tx_bits, mod_type)
papr_values = self._calculate_papr_values(syms, n_fft, nc)
```

Primero obtiene `n_fft` y `nc`, que son el tamano de FFT y el numero de
subportadoras activas para el ancho de banda seleccionado. Luego aplica
scrambling a los bits de la imagen y mapea esos bits a simbolos complejos segun
la modulacion elegida.

El arreglo `syms` contiene la secuencia QPSK, 16-QAM o 64-QAM que sera
empaquetada en bloques OFDM para medir PAPR.

### Funcion `_calculate_papr_values`

Esta es la funcion que calcula el PAPR de cada bloque OFDM.

Primero determina cuantas subportadoras se usan como pilotos y cuantas quedan
para datos:

```python
first_pilot_mask = ofdm_ops.pilot_subcarrier_mask(nc)
data_per_block = nc - int(np.sum(first_pilot_mask))
```

`first_pilot_mask` es un arreglo booleano de longitud `nc`. Tiene `True` en las
posiciones donde se insertan pilotos para el primer bloque. El patron base es
cada 6 subportadoras; en bloques alternos se desplaza 3 subportadoras para usar
la misma idea de estimacion que la transmision de imagen.

Despues se calcula cuantos bloques OFDM hacen falta:

```python
num_blocks = int(np.ceil(num_symbols / data_per_block)) if num_symbols else 0
```

Si los simbolos no llenan exactamente el ultimo bloque, se agrega padding con
ceros complejos:

```python
padded = np.zeros(num_blocks * data_per_block, dtype=np.complex128)
padded[:num_symbols] = symbols
data_grid = padded.reshape(num_blocks, data_per_block)
```

Luego se arma la grilla activa de subportadoras:

```python
active_grid = np.zeros((num_blocks, nc), dtype=np.complex128)
active_grid[:, pilot_mask] = ofdm_ops.pilot_symbol_grid(num_blocks, int(np.sum(pilot_mask)))
active_grid[:, data_mask] = data_grid
```

Cada fila de `active_grid` representa un bloque OFDM en frecuencia. Las columnas
son las `nc` subportadoras activas. En las posiciones de pilotos se insertan
simbolos QPSK deterministicos y en las posiciones restantes se insertan los
datos de la imagen.

Para el sobremuestreo se crea una FFT mas grande:

```python
os_fft = n_fft * self.papr_oversampling
freq_grid = np.zeros((num_blocks, os_fft), dtype=np.complex128)
freq_grid[:, ofdm_ops.active_subcarrier_indices(os_fft, nc)] = active_grid
```

Aqui `os_fft` es `4 * n_fft`. La funcion
`ofdm_ops.active_subcarrier_indices(os_fft, nc)` coloca las mismas `nc`
subportadoras activas alrededor de DC, pero dentro de una grilla de frecuencia
mas larga. El resto de posiciones queda en cero, lo que equivale a zero-padding
en frecuencia para obtener mas muestras temporales.

Luego se aplica la IFFT:

```python
time_grid = np.fft.ifft(freq_grid, axis=1) * np.sqrt(os_fft)
```

El resultado `time_grid` tiene una fila por bloque OFDM y `os_fft` muestras
temporales por bloque. El factor `sqrt(os_fft)` mantiene una normalizacion de
potencia consistente con el resto del simulador.

Despues se calcula la potencia instantanea de cada muestra:

```python
power = np.abs(time_grid) ** 2
avg_pwr = np.mean(power, axis=1)
```

`power` contiene `|x[n]|^2` para cada muestra de cada bloque. `avg_pwr` contiene
la potencia media de cada bloque OFDM.

Finalmente se calcula el PAPR en dB por bloque:

```python
valid = avg_pwr > 0
return 10 * np.log10(np.max(power[valid], axis=1) / avg_pwr[valid])
```

El filtro `valid` evita divisiones por cero. La salida es un arreglo
unidimensional: cada elemento corresponde al PAPR de un bloque OFDM.

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
