# Arquitectura y modularizacion del codigo

Este documento explica como esta organizado el proyecto, que responsabilidad
tiene cada modulo y como se conectan las partes principales del simulador
LTE-OFDM.

## Vision general

El proyecto esta dividido en capas para separar la interfaz grafica, la
coordinacion de simulaciones y el nucleo matematico:

```text
main.py
  |
  v
ui/main_window.py
  |
  v
controller/simulation_mgr.py
  |
  v
core/config.py
core/utils.py
core/ofdm_ops.py
core/channel.py
```

La idea central de esta modularizacion es que la interfaz no contenga las
operaciones matematicas de OFDM, y que el nucleo `core/` no dependa de la GUI.
Asi, las pruebas unitarias pueden validar el procesamiento numerico sin abrir
la ventana.

## Capas del proyecto

### 1. Entrada de la aplicacion

Archivo principal: `main.py`

Es el punto de arranque. Ajusta la ruta para que Python encuentre los paquetes
locales, importa `MainWindow` y ejecuta el ciclo principal de CustomTkinter.

No contiene logica de simulacion. Su responsabilidad es iniciar la aplicacion.

### 2. Interfaz grafica

Carpeta: `ui/`

Contiene la ventana, los controles de usuario, las pestanas de visualizacion y
las graficas embebidas con Matplotlib.

La interfaz recoge parametros como ancho de banda, prefijo ciclico, modulacion,
SNR, cantidad de caminos del canal e imagen seleccionada. Luego delega el
calculo a `controller/simulation_mgr.py`.

Tambien usa un worker thread para que calculos pesados, como BER Monte Carlo o
PAPR, no congelen la ventana.

### 3. Controlador de simulacion

Carpeta: `controller/`

Actua como puente entre la GUI y el nucleo matematico. Recibe parametros ya
codificados desde la interfaz, ejecuta la cadena completa Tx/canal/Rx y devuelve
diccionarios listos para mostrar en pantalla.

Aqui se decide el flujo de alto nivel:

```text
imagen -> bits -> scrambling -> modulacion digital -> OFDM con pilotos
       -> prefijo ciclico -> canal Rayleigh + AWGN -> quitar CP
       -> FFT + estimacion de canal -> demapeo -> descrambling
       -> BER + reconstruccion de imagen
```

El controlador tambien calcula curvas comparativas de BER y PAPR para QPSK,
16-QAM y 64-QAM.

### 4. Nucleo matematico

Carpeta: `core/`

Contiene funciones reutilizables, sin dependencia de la interfaz grafica.
Esta capa concentra:

- parametros LTE simplificados;
- conversion entre imagenes y bits;
- scrambling;
- mapeo y demapeo QPSK/16-QAM/64-QAM;
- modulacion y demodulacion OFDM;
- insercion de pilotos;
- prefijo ciclico;
- canal Rayleigh multipath;
- ruido AWGN;
- reportes de seguridad del prefijo ciclico.

## Estructura de archivos

```text
.
|-- main.py
|-- requirementsP5.txt
|-- README.md
|-- ARQUITECTURA_CODIGO.md
|-- FLUJO_IMAGEN.md
|-- PAPR.md
|-- FUENTES.md
|-- AUDITORIA_FINAL.md
|-- controller/
|   |-- __init__.py
|   `-- simulation_mgr.py
|-- core/
|   |-- __init__.py
|   |-- config.py
|   |-- utils.py
|   |-- ofdm_ops.py
|   `-- channel.py
|-- ui/
|   |-- __init__.py
|   `-- main_window.py
|-- tests/
|   |-- __init__.py
|   `-- test_core.py
`-- imagenes/
    |-- baboon.png
    |-- boat.png
    |-- cameraman.jpg
    |-- clock.png
    `-- peppers.png
```

Los directorios `venv/` y `__pycache__/` son artefactos locales generados por
Python o por el entorno virtual. No forman parte de la arquitectura fuente del
simulador.

## Que contiene cada archivo

### `main.py`

Punto de entrada del programa.

Responsabilidades:

- preparar la ruta local del proyecto;
- importar `MainWindow`;
- crear la ventana principal;
- iniciar `app.mainloop()`.

No procesa imagenes, no calcula BER y no implementa OFDM.

### `ui/main_window.py`

Define la clase `MainWindow`, que hereda de `customtkinter.CTk`.

Responsabilidades principales:

- construir la interfaz grafica;
- mostrar selectores de ancho de banda, CP, modulacion, SNR y caminos;
- permitir seleccionar imagenes con `filedialog`;
- mostrar imagen transmitida e imagen recibida;
- crear las pestanas de BER y PAPR;
- incrustar graficas de Matplotlib dentro de la ventana;
- ejecutar simulaciones en un hilo secundario;
- recibir resultados del worker mediante una cola;
- actualizar la interfaz con los resultados.

Funciones importantes:

- `setup_ui`: arma el layout de la ventana.
- `select_file`: guarda la ruta de la imagen seleccionada.
- `action_run_image`: inicia la transmision de imagen.
- `action_plot_ber`: inicia el calculo de curva BER.
- `action_plot_papr`: inicia el calculo de PAPR.
- `_start_worker`: lanza un calculo en segundo plano.
- `_poll_worker_queue`: revisa si el worker ya termino.
- `_show_image_result`: actualiza la vista de imagenes.
- `_show_ber_result`: dibuja la curva BER.
- `_show_papr_result`: dibuja la CCDF de PAPR.
- `embed_multi_plot`: genera graficas comparativas.

Esta capa no implementa directamente la cadena OFDM; llama al controlador.

### `controller/simulation_mgr.py`

Define la clase `OFDMSimulationManager`.

Es el coordinador principal de la simulacion. Toma los parametros recibidos
desde la GUI y llama a las funciones de `core/` en el orden correcto.

Responsabilidades principales:

- fijar el tamano interno de imagen en `250x250`;
- ejecutar la transmision completa de una imagen;
- calcular BER de una corrida;
- reconstruir la imagen recibida;
- calcular curvas BER vs SNR con Monte Carlo;
- calcular intervalos de confianza al 95%;
- comparar QPSK, 16-QAM y 64-QAM;
- calcular la distribucion PAPR/CCDF;
- preparar resumenes de configuracion para la GUI.

Funciones y metodos relevantes:

- `run_image_transmission`: ejecuta Tx, canal y Rx para una imagen.
- `_prepare_tx_signal`: prepara bits, scrambling, simbolos, OFDM y CP.
- `_receive_bits`: procesa recepcion, FFT, pilotos, demapeo y descrambling.
- `calculate_ber_curve`: calcula BER vs SNR para las tres modulaciones.
- `_calculate_ber_series`: ejecuta Monte Carlo por modulacion.
- `calculate_papr_distribution`: calcula CCDF de PAPR para las tres modulaciones.
- `_calculate_papr_values`: obtiene el PAPR por bloque OFDM.
- `_wilson_interval`, `_mean_interval`, `_combined_interval`: calculan bandas de confianza.

Este archivo es el lugar donde se arma el experimento, pero no define las
constelaciones ni el canal desde cero; eso vive en `core/`.

### `core/config.py`

Contiene constantes de configuracion LTE y parametros globales del simulador.

Responsabilidades principales:

- definir el espaciamiento de subportadoras `15 kHz`;
- definir la FFT de referencia `2048`;
- mapear anchos de banda LTE a RB, subportadoras activas y tamano FFT;
- definir perfiles de prefijo ciclico normal y extendido;
- definir nombres y bits por simbolo para QPSK, 16-QAM y 64-QAM;
- definir parametros de pilotos, como espaciamiento y semilla.

Estructuras importantes:

- `LTE_BANDWIDTHS`: tabla de ancho de banda, RB, subportadoras y FFT.
- `LTE_PROFILES`: perfiles de prefijo ciclico.
- `MODULATION_NAMES`: nombres legibles de modulacion.
- `MODULATION_BITS`: bits por simbolo.
- `PILOT_SPACING_SC`: separacion de pilotos.
- `PILOT_SEED`: semilla de pilotos deterministicos.

Este archivo evita que valores fisicos queden repetidos en varios modulos.

### `core/utils.py`

Agrupa utilidades de imagen, bits, scrambling y modulacion digital.

Responsabilidades principales:

- obtener parametros OFDM a partir de indices de GUI;
- escalar longitudes de prefijo ciclico;
- leer imagenes en escala de grises;
- redimensionar imagenes al tamano interno;
- convertir pixeles a bits con `numpy.unpackbits`;
- reconstruir imagenes desde bits con `numpy.packbits`;
- aplicar scrambling por XOR;
- mapear bits a simbolos QPSK/16-QAM/64-QAM;
- demapear simbolos complejos a bits por distancia minima.

Funciones importantes:

- `get_cp_lengths`: escala CP segun `n_fft`.
- `get_ofdm_params`: devuelve `n_fft`, subportadoras, CP y `delta_f`.
- `image_to_bits`: carga imagen y la convierte en bits.
- `bits_to_image`: reconstruye matriz de imagen desde bits.
- `map_bits_to_symbols`: modulador digital.
- `demap_symbols_to_bits`: demodulador por maxima verosimilitud/distancia minima.
- `apply_scrambling`: aplica o revierte scrambling con XOR.

### `core/ofdm_ops.py`

Implementa operaciones propias de OFDM.

Responsabilidades principales:

- ubicar subportadoras activas alrededor de DC;
- dejar DC vacia;
- insertar pilotos conocidos;
- empaquetar simbolos en bloques OFDM;
- aplicar IFFT para pasar al dominio temporal;
- agregar prefijo ciclico;
- retirar prefijo ciclico;
- aplicar FFT en recepcion;
- estimar canal usando pilotos;
- interpolar la respuesta de canal;
- ecualizar datos recibidos.

Funciones importantes:

- `active_subcarrier_indices`: devuelve indices FFT activos.
- `pilot_subcarrier_mask`: marca posiciones de pilotos.
- `pilot_symbol_grid`: genera pilotos QPSK deterministicos.
- `modulate_ofdm`: OFDM sin pilotos.
- `modulate_ofdm_with_pilots`: OFDM con pilotos.
- `add_cyclic_prefix`: inserta CP por bloque.
- `remove_cyclic_prefix`: elimina CP.
- `demodulate_ofdm`: recupera subportadoras activas.
- `demodulate_ofdm_with_pilots`: estima canal, ecualiza y devuelve datos.
- `equalize_channel`: ecualizador Zero-Forcing usando una respuesta conocida.

Este archivo trabaja con arreglos complejos y no sabe nada de imagenes o GUI.

### `core/channel.py`

Modela el canal inalambrico simplificado.

Responsabilidades principales:

- definir perfiles de canal, incluido el perfil didactico de CP y perfiles ITU Rayleigh;
- describir retardos, ganancias y retardos discretizados por muestras;
- verificar si el retardo maximo cabe dentro del CP;
- generar canales Rayleigh multipath;
- aplicar convolucion con el canal;
- agregar ruido AWGN con una SNR indicada.

Estructuras y funciones importantes:

- `CHANNEL_PROFILES`: perfil didactico de CP y perfiles Pedestrian/Vehicular.
- `DEFAULT_RAYLEIGH_PROFILE`: perfil por defecto, `Didactico CP`.
- `get_rayleigh_profile`: devuelve una copia del perfil.
- `describe_rayleigh_paths`: resume caminos activos.
- `cp_safety_report`: indica margen entre retardo maximo y CP minimo.
- `generate_rayleigh_channel`: genera la respuesta impulsiva.
- `apply_awgn`: agrega ruido blanco gaussiano complejo.
- `apply_rayleigh`: aplica canal multipath y ruido.

El canal se mantiene educativo: no modela Doppler, sincronizacion imperfecta ni
no linealidades RF.

### `tests/test_core.py`

Contiene pruebas unitarias del nucleo y smoke tests del controlador.

Responsabilidades principales:

- validar parametros LTE usados por el simulador;
- comprobar puntos de constelaciones QPSK/16-QAM/64-QAM;
- verificar ida y vuelta de modulacion/demodulacion;
- comprobar scrambling y descrambling;
- probar OFDM con CP variable;
- probar OFDM con pilotos y estimacion de canal;
- validar propiedades del canal Rayleigh discretizado;
- verificar que pilotos sean deterministicos;
- ejecutar una transmision completa con `OFDMSimulationManager`;
- comprobar salidas de BER y PAPR.

Se ejecuta con:

```bash
venv/bin/python -m unittest discover -v
```

### `requirementsP5.txt`

Lista dependencias Python necesarias para ejecutar el proyecto.

Incluye librerias para:

- interfaz grafica (`customtkinter`);
- graficas (`matplotlib`);
- operaciones numericas (`numpy`);
- lectura/procesamiento de imagenes (`opencv-python`, `Pillow`);
- utilidades requeridas por esas librerias.

### `README.md`

Documento principal de uso del proyecto.

Resume:

- caracteristicas;
- instalacion;
- ejecucion;
- estructura general;
- flujo de simulacion;
- parametros LTE;
- limitaciones;
- comandos utiles.

Es el primer documento que conviene leer para correr la aplicacion.

### `FLUJO_IMAGEN.md`

Explica paso a paso que ocurre con una imagen desde que se selecciona en la GUI
hasta que se reconstruye en recepcion.

Es mas detallado que el README para la cadena de imagen:

```text
seleccion -> bits -> scrambling -> simbolos -> OFDM -> canal -> receptor -> imagen
```

Tambien referencia funciones concretas donde vive cada etapa.

### `PAPR.md`

Documento tecnico sobre el calculo de PAPR.

Explica:

- que significa PAPR;
- como se calcula por bloque OFDM;
- como se construye la CCDF;
- por que se usa sobremuestreo `L=4`;
- por que el canal, la SNR y el CP no aplican al calculo actual;
- que limitaciones tiene el analisis.

### `FUENTES.md`

Documento de soporte bibliografico y tecnico.

Separa:

- parametros tomados de fuentes LTE/3GPP/ETSI/ITU;
- decisiones propias del simulador educativo.

Sirve para justificar numerologia, resource blocks, prefijo ciclico,
modulaciones y perfiles Rayleigh.

### `AUDITORIA_FINAL.md`

Resumen de revision tecnica del proyecto.

Indica:

- que partes son coherentes con LTE-OFDM;
- que partes son simplificaciones didacticas;
- riesgos revisados;
- comandos de validacion;
- veredicto de presentabilidad academica.

### `imagenes/`

Contiene imagenes de prueba para transmitir por la cadena OFDM.

Archivos actuales:

- `cameraman.jpg`: imagen clasica cercana a `250x250`; buena para pruebas base.
- `clock.png`: imagen clasica de `256x256`; util para bordes y formas suaves.
- `boat.png`: escena natural clasica.
- `peppers.png`: imagen clasica de procesamiento de imagenes.
- `baboon.png`: imagen con mucha textura, util para estresar la transmision.

El simulador siempre lee la imagen en escala de grises y la redimensiona a
`250x250` antes de transmitirla.

### `__init__.py`

Aparece en `core/`, `controller/`, `ui/` y `tests/`.

Su funcion es marcar esas carpetas como paquetes Python. En este proyecto no
contienen logica relevante, pero ayudan a que los imports funcionen de forma
ordenada.

## Flujo de dependencias

La dependencia principal fluye en una sola direccion:

```text
ui -> controller -> core
```

Detalles:

- `main.py` importa `ui.main_window.MainWindow`.
- `ui/main_window.py` importa `controller.simulation_mgr.OFDMSimulationManager`.
- `ui/main_window.py` tambien usa `core.channel` y `core.utils` para mostrar informacion del canal en la GUI.
- `controller/simulation_mgr.py` importa `core.config`, `core.utils`, `core.ofdm_ops` y `core.channel`.
- `core/utils.py` importa parametros desde `core.config`.
- `core/ofdm_ops.py` importa parametros de pilotos desde `core.config`.
- `core/channel.py` solo depende de `numpy`.

Esto mantiene el nucleo reutilizable y testeable.

## Flujo de una transmision de imagen

La transmision manual se ejecuta asi:

1. `MainWindow.select_file` guarda la ruta de la imagen.
2. `MainWindow.action_run_image` lee parametros de la GUI.
3. `_start_worker` ejecuta `OFDMSimulationManager.run_image_transmission` en un hilo secundario.
4. `run_image_transmission` obtiene parametros LTE con `utils.get_ofdm_params`.
5. `utils.image_to_bits` carga la imagen, la pasa a gris y la convierte a bits.
6. `utils.apply_scrambling` aplica scrambling XOR.
7. `utils.map_bits_to_symbols` genera simbolos QPSK, 16-QAM o 64-QAM.
8. `ofdm_ops.modulate_ofdm_with_pilots` inserta pilotos y aplica IFFT.
9. `ofdm_ops.add_cyclic_prefix` agrega CP.
10. `channel.apply_rayleigh` aplica canal Rayleigh y AWGN.
11. `ofdm_ops.remove_cyclic_prefix` quita CP.
12. `ofdm_ops.demodulate_ofdm_with_pilots` aplica FFT, estima canal y ecualiza.
13. `utils.demap_symbols_to_bits` recupera bits.
14. `utils.apply_scrambling` revierte scrambling.
15. `utils.bits_to_image` reconstruye la imagen.
16. El controlador calcula BER y devuelve resultados.
17. `_show_image_result` actualiza imagenes y texto de estado en la GUI.

## Flujo de BER

La curva BER se inicia desde `MainWindow.action_plot_ber` y se calcula en
`OFDMSimulationManager.calculate_ber_curve`.

Caracteristicas:

- usa la imagen cargada como carga util;
- compara siempre QPSK, 16-QAM y 64-QAM;
- evalua un rango de SNR entre 0 y 30 dB;
- usa Monte Carlo;
- calcula intervalos de confianza al 95%;
- reporta cuantas corridas se usaron por punto;
- muestra los bloques OFDM requeridos por modulacion.

## Flujo de PAPR

La curva PAPR se inicia desde `MainWindow.action_plot_papr` y se calcula en
`OFDMSimulationManager.calculate_papr_distribution`.

Caracteristicas:

- usa la imagen cargada;
- compara QPSK, 16-QAM y 64-QAM;
- calcula PAPR antes del CP y antes del canal;
- usa sobremuestreo `L=4`;
- construye una CCDF empirica;
- no usa Monte Carlo en la version actual.

## Criterio de modularizacion

La organizacion adoptada evita mezclar responsabilidades:

- `ui/`: presentacion, controles, eventos y graficas.
- `controller/`: coordinacion de experimentos y formato de resultados.
- `core/`: operaciones matematicas reutilizables.
- `tests/`: validacion automatica.
- documentos `.md`: explicacion, fuentes, auditoria y guias de uso.
- `imagenes/`: datos de entrada de ejemplo.

Esta separacion facilita cambiar una parte sin reescribir las demas. Por
ejemplo, se podria reemplazar CustomTkinter por otra interfaz manteniendo buena
parte de `controller/` y `core/`, o se podria agregar otro modelo de canal
modificando `core/channel.py` sin tocar la GUI.

## Comandos utiles para validar

Compilar fuentes Python:

```bash
venv/bin/python -m compileall main.py controller core ui tests
```

Ejecutar pruebas:

```bash
venv/bin/python -m unittest discover -v
```

Ejecutar aplicacion:

```bash
venv/bin/python main.py
```
