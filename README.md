# Simulador LTE MIMO-OFDM

Aplicacion de escritorio en Python para simular la transmision de una imagen mediante una cadena LTE-OFDM simplificada con multiplexacion espacial MIMO 2x2, extension 4x4 y comparacion multiantena 4x2 con precoding fijo. La interfaz se centra en modulacion, SNR, imagen de referencia y analisis multiantena; el ancho de banda, prefijo ciclico, multipath, modo MIMO y detector quedan como valores internos de la comparativa para reducir ruido visual.

## Caracteristicas

- Interfaz grafica con CustomTkinter.
- Simulaciones pesadas ejecutadas en un worker thread para mantener la interfaz responsiva.
- Transmision de imagenes en escala de grises.
- Modulaciones QPSK, 16-QAM y 64-QAM.
- Modulacion y demodulacion OFDM con IFFT/FFT.
- Prefijo ciclico normal y extendido.
- Canal multipath con perfil `ITU Vehicular B` por defecto, perfil didactico `Didactico CP` disponible y ruido AWGN.
- OFDM simplificado sin subportadoras reservadas de referencia: todas las subportadoras activas transportan datos.
- Ecualizacion y deteccion usando CSI directa: el receptor usa el mismo canal generado por la simulacion.
- Modos `SISO 1x1`, `SM 2x2`, `SM 4x2` y `SM 4x4` de multiplexacion espacial.
- `SM 4x2` usa 4 antenas TX, 2 antenas RX, 2 capas y un precoder fijo semiunitario.
- Deteccion MIMO por subportadora con ZF, IRC/MMSE o MMSE-SIC.
- Comparacion multiantena visual y BER con bits aleatorios entre escenarios `2x2`, `4x2` y `4x4`, usando `IRC/MMSE` y `SIC`.
- Selector de rank para comparar BER en `Rank 2` o en `Rank maximo`.

## Requisitos

- Python 3.12 o compatible.
- Tkinter disponible en el sistema.
- Dependencias listadas en `requirementsP5.txt`.

En Linux, si Tkinter no esta instalado, puede requerirse el paquete del sistema correspondiente, por ejemplo `python3-tk`.

## Instalacion

Desde la raiz del proyecto:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirementsP5.txt
```

En este proyecto el entorno virtual local se llama `venv/` y esta ignorado por `.gitignore`.

## Ejecucion

Con el entorno virtual activado:

```bash
python main.py
```

O sin activar el entorno:

```bash
venv/bin/python main.py
```

Al abrir la aplicacion:

1. Selecciona la modulacion.
2. Ajusta la SNR.
3. Elige una imagen desde el boton "Seleccionar Imagen..." si quieres generar la prueba visual.
4. Selecciona `Rank 2` para una comparacion BER mas justa o `Rank maximo` para mostrar la extension 4x4 completa.
5. Usa "PRUEBA MULTIANTENA" o "CURVAS BER".

La pestana "Imagen Original" muestra solo la imagen seleccionada como referencia. `PRUEBA MULTIANTENA` usa esa imagen para generar una grilla visual de seis reconstrucciones. `CURVAS BER` usa bits aleatorios para comparar `2x2`, `4x2` y `4x4` con `IRC/MMSE` y `SIC`. En `Rank 2`, tambien el caso `4x4` transmite dos capas; en `Rank maximo`, `4x4` transmite cuatro capas.

## Estructura Del Proyecto

```text
.
|-- main.py
|-- requirementsP5.txt
|-- FUENTES.md
|-- controller/
|   `-- simulation_mgr.py
|-- core/
|   |-- channel.py
|   |-- config.py
|   |-- ofdm_ops.py
|   `-- utils.py
|-- ui/
|   `-- main_window.py
|-- tests/
|   |-- __init__.py
|   `-- test_core.py
`-- imagenes/
    |-- baboon.png
    |-- boat.png
    |-- cameraman.jpg
    `-- peppers.png
```

## Flujo De Simulacion

La cadena principal esta en `controller/simulation_mgr.py`.

1. La imagen se carga en escala de grises y se redimensiona a `250x250`.
2. La matriz de pixeles se convierte a bits con `numpy.unpackbits`.
3. Se aplica scrambling por XOR usando una semilla fija.
4. Los bits se mapean a simbolos complejos segun las constelaciones LTE.
5. En SISO, los simbolos se agrupan en subportadoras OFDM centradas alrededor de DC.
6. En MIMO, los simbolos se dividen round-robin en capas espaciales; `4x2` transmite 2 capas sobre 4 antenas TX mediante precoding fijo.
7. Se aplica IFFT para pasar al dominio temporal en cada antena TX.
8. Se inserta prefijo ciclico por bloque OFDM.
9. La senal pasa por el canal Rayleigh multipath SISO o MIMO y se agrega ruido AWGN.
10. En recepcion se retira el prefijo ciclico.
11. Se aplica FFT para recuperar las subportadoras.
12. El receptor usa directamente el canal generado por la simulacion para construir `H[k]`.
13. Se ecualiza SISO o se detectan las capas MIMO con ZF, IRC/MMSE o MMSE-SIC.
14. Se demapean simbolos a bits.
15. Se revierte el scrambling.
16. Se calcula BER y se reconstruye la imagen recibida.

Para la curva BER Monte Carlo se generan bits aleatorios reproducibles como carga util. Esto permite comparar modulaciones y arreglos MIMO sin depender del contenido de una imagen particular. La UI usa por defecto `10 MHz`, CP normal y un camino multipath, manteniendo esos parametros fuera del panel principal. La comparacion multiantena repite la simulacion para 2x2, 4x2 y 4x4 con detectores IRC/MMSE y SIC usando la modulacion seleccionada.

La transmision manual de imagen usa por defecto una semilla fija (`image_tx_seed = 2024`) para que repetir la misma configuracion produzca la misma realizacion de canal y ruido. Esto facilita comparar visualmente cambios de SNR, modulacion, CP o numero de caminos. Para pruebas automatizadas, `run_image_transmission` tambien acepta `rng_seed`, lo que permite sobrescribir esa realizacion reproducible.

El numero de simbolos mostrado depende de la modulacion: QPSK agrupa 2 bits por simbolo, 16-QAM agrupa 4 y 64-QAM agrupa 6. Si la cantidad de bits no calza exactamente, el modulador agrega padding al final antes de generar los simbolos. El numero de bloques OFDM indica cuantas IFFT/bloques temporales fueron necesarios para transportar esos simbolos usando todas las subportadoras activas como datos.

## Parametros LTE Implementados

Los parametros estan definidos en `core/config.py`.

| Opcion | Ancho de banda | Resource blocks | Subportadoras activas | FFT |
| --- | ---: | ---: | ---: | ---: |
| 1 | 1.4 MHz | 6 | 72 | 128 |
| 2 | 3 MHz | 15 | 180 | 256 |
| 3 | 5 MHz | 25 | 300 | 512 |
| 4 | 10 MHz | 50 | 600 | 1024 |
| 5 | 15 MHz | 75 | 900 | 1536 |
| 6 | 20 MHz | 100 | 1200 | 2048 |

El prefijo ciclico normal usa un primer simbolo mas largo por slot y seis simbolos posteriores mas cortos. El prefijo extendido usa seis simbolos por slot con CP constante. Ambos patrones se escalan desde la referencia LTE de FFT 2048.

## Modulos Principales

- `main.py`: punto de entrada de la aplicacion.
- `ui/main_window.py`: interfaz grafica, controles, pestanas y graficas embebidas.
- `controller/simulation_mgr.py`: coordina transmisor, canal, receptor, BER y comparacion MIMO.
- `core/config.py`: tablas de ancho de banda, prefijo ciclico y constelaciones.
- `core/utils.py`: conversion imagen/bits, scrambling y mapeo/demapeo digital.
- `core/ofdm_ops.py`: modulacion OFDM, prefijo ciclico, FFT/IFFT y ecualizacion.
- `core/channel.py`: canal AWGN y multipath con perfiles ITU y un perfil didactico discretizados.
- `tests/test_core.py`: pruebas de parametros, constelaciones, OFDM y smoke test del controlador.
- `FUENTES.md`: fuentes 3GPP/ETSI de los parametros LTE usados.

## Mejoras Tecnicas Aplicadas

- Constelaciones QPSK, 16-QAM y 64-QAM alineadas con el mapeo LTE.
- Mapeo/demapeo vectorizado con NumPy y cache de constelaciones.
- Subportadoras OFDM distribuidas alrededor de DC, dejando DC vacia.
- Prefijo ciclico normal variable por simbolo de slot.
- FFT de 15 MHz corregida a 1536.
- Perfil por defecto `ITU Vehicular B`, discretizado con `Fs = NFFT * Delta_f` y potencia media del PDP normalizada.
- Perfil `Didactico CP`, no ITU, disponible en `core/channel.py` para pruebas controladas del efecto CP: usa un camino directo y un eco a `12 us`.
- La interfaz oculta BW, CP y multipath para centrar la practica en MIMO; internamente usa `10 MHz`, CP normal y un camino multipath.
- OFDM simplificado para la practica MIMO: no reserva subportadoras de referencia y usa todas las subportadoras activas para datos.
- Multiplexacion espacial SU-MIMO 2x2, 4x2 y 4x4 con CSI directa tomada del canal generado.
- Comparacion `4x2` con 2 capas y precoder fijo `1/sqrt(2) * [[1,0], [0,1], [1,0], [0,1]]`, de modo que el receptor detecta sobre `H_eff = H @ W`.
- Detectores lineales ZF e IRC/MMSE por subportadora, alineados con la explicacion de recuperacion mediante `W = H^-1` y su variante regularizada frente a ruido.
- Detector `MMSE-SIC` opcional: decide una capa, cuantiza al punto QAM LTE mas cercano, cancela su interferencia y continua con las capas restantes.
- Canal Rayleigh MIMO con realizaciones independientes por enlace TX-RX y potencia total escalada por `1/sqrt(layers)`.
- Metricas de exposicion: condicion media/mediana de `H[k]`, capacidad ideal aproximada en bps/Hz y numero de capas.
- Aviso de margen CP/retardo para detectar posibles condiciones de ISI.
- Curva BER multi-modulacion con Monte Carlo sobre bits aleatorios e intervalos de confianza al 95%.
- Comparacion visual multiantena sobre la imagen cargada y BER multiantena sobre bits aleatorios para 2x2/4x2/4x4 con IRC/MMSE y SIC.
- Worker thread para el analisis MIMO, evitando que la ventana se congele mientras calcula.
- Pruebas automatizadas con `unittest`.

## Validacion Rapida

Puedes comprobar que el nucleo funciona sin abrir la GUI:

```bash
venv/bin/python - <<'PY'
from controller.simulation_mgr import OFDMSimulationManager

manager = OFDMSimulationManager()
result = manager.run_image_transmission(
    "imagenes/cameraman.jpg",
    bw_idx=4,
    profile_idx=1,
    mod_type=2,
    snr_db=15,
    num_paths=1,
    rng_seed=manager.mc_seed,
    mimo_mode=2,
    detector=2,
)

print(result["success"])
print(result.get("ber"))
PY
```

Tambien puedes verificar que la ventana se crea correctamente:

```bash
venv/bin/python - <<'PY'
from ui.main_window import MainWindow

app = MainWindow()
app.update_idletasks()
app.update()
print("GUI OK")
app.destroy()
PY
```

Para correr todas las pruebas:

```bash
venv/bin/python -m unittest discover -v
```

## Limitaciones Conocidas

- Es una simulacion educativa de LTE-OFDM, no una implementacion LTE completa.
- El receptor asume sincronizacion perfecta.
- El receptor usa CSI directa del canal generado; no modela sincronizacion ni estimacion real de canal.
- El canal Rayleigh usa taps estaticos durante cada transmision o corrida; no modela aun variacion temporal Jakes/Doppler.
- MIMO se limita a SU-MIMO `2x2`, `4x2` con precoder fijo y extension didactica `4x4`; no implementa MU-MIMO, precodificacion por libro de codigos ni ML.
- No modela el grid completo LTE con tramas, slots, canales fisicos, codificacion, HARQ ni senalizacion de referencia LTE completa.
- Las simulaciones largas se ejecutan en un worker thread; aun no hay boton de cancelacion ni progreso por corrida.
- La imagen siempre se procesa como escala de grises de `250x250`.

## Comandos Utiles

Instalar dependencias:

```bash
venv/bin/python -m pip install -r requirementsP5.txt
```

Ejecutar la app:

```bash
venv/bin/python main.py
```

Probar sintaxis del codigo fuente:

```bash
venv/bin/python -m compileall main.py controller core ui tests
```

Ejecutar pruebas:

```bash
venv/bin/python -m unittest discover -v
```
