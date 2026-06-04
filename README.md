# Simulador LTE OFDM

Aplicacion de escritorio en Python para simular la transmision de una imagen mediante una cadena LTE-OFDM simplificada. Permite configurar ancho de banda, prefijo ciclico, modulacion, SNR y numero de caminos del canal, y luego visualizar la imagen transmitida, la imagen recibida, la curva BER y la distribucion PAPR.

## Caracteristicas

- Interfaz grafica con CustomTkinter.
- Simulaciones pesadas ejecutadas en un worker thread para mantener la interfaz responsiva.
- Transmision de imagenes en escala de grises.
- Modulaciones QPSK, 16-QAM y 64-QAM.
- Modulacion y demodulacion OFDM con IFFT/FFT.
- Prefijo ciclico normal y extendido.
- Canal multipath con perfil `ITU Vehicular B` por defecto, perfil didactico `Didactico CP` disponible y ruido AWGN.
- Pilotos OFDM QPSK deterministas cada 6 subportadoras activas, con desplazamiento alternado entre bloques.
- Ecualizacion usando una estimacion de canal DFT/LS regularizada desde pilotos.
- Calculo Monte Carlo de BER sobre los bits reales de la imagen, comparando QPSK, 16-QAM y 64-QAM en una sola grafica.
- Calculo empirico de CCDF de PAPR para QPSK, 16-QAM y 64-QAM usando la imagen cargada.
- Intervalos de confianza al 95% en la curva BER.

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

1. Selecciona un ancho de banda LTE.
2. Selecciona el tipo de prefijo ciclico.
3. Selecciona la modulacion.
4. Ajusta la SNR y el numero de caminos multipath.
5. Elige una imagen desde el boton "Seleccionar Imagen...".
6. Usa "TRANSMITIR IMAGEN", "GENERAR CURVA BER" o "ANALIZAR PAPR".

La transmision de imagen muestra BER, bits totales de la imagen, simbolos modulados, bloques OFDM requeridos y subportadoras activas. La curva BER siempre compara QPSK, 16-QAM y 64-QAM, sin depender de la modulacion seleccionada en la interfaz. La curva BER muestra el punto estimado, una banda sombreada con intervalo de confianza al 95%, las corridas Monte Carlo usadas por punto y la configuracion fisica usada. La curva PAPR tambien compara las tres modulaciones, pero es una CCDF empirica sin Monte Carlo; su resumen indica los bloques OFDM evaluados y aclara que CP/canal no aplican al calculo.

## Estructura Del Proyecto

```text
.
|-- main.py
|-- requirementsP5.txt
|-- PAPR.md
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
5. Los simbolos se agrupan en subportadoras OFDM centradas alrededor de DC.
6. Se insertan pilotos QPSK conocidos cada 6 subportadoras activas, alternando el desplazamiento entre bloques.
7. Se aplica IFFT para pasar al dominio temporal.
8. Se inserta prefijo ciclico por bloque OFDM.
9. La senal pasa por el canal Rayleigh multipath y se agrega ruido AWGN.
10. En recepcion se retira el prefijo ciclico.
11. Se aplica FFT para recuperar las subportadoras.
12. Se estima el canal con los pilotos mediante un ajuste DFT/LS regularizado y se reconstruye `H[k]`.
13. Se ecualizan las subportadoras de datos con el canal estimado.
14. Se demapean simbolos a bits.
15. Se revierte el scrambling.
16. Se calcula BER y se reconstruye la imagen recibida.

Para la curva BER Monte Carlo no se generan bits aleatorios como carga util. Cada corrida parte de la misma imagen cargada y repite la transmision completa con nuevas realizaciones de ruido/canal y scrambling de la imagen para QPSK, 16-QAM y 64-QAM. El resumen de BER muestra cuantas corridas por punto fueron necesarias, el ancho de banda, subportadoras activas, CP, perfil de canal activo, caminos multipath y bloques OFDM por corrida para cada modulacion. En PAPR no se usa Monte Carlo: se calcula una CCDF empirica por modulacion sobre los bloques OFDM generados desde la imagen cargada. Como PAPR se mide antes del CP y antes del canal, el resumen solo reporta ancho de banda, subportadoras activas, bloques evaluados y `CP/canal: no aplican`.

La transmision manual de imagen usa por defecto una semilla fija (`image_tx_seed = 2024`) para que repetir la misma configuracion produzca la misma realizacion de canal y ruido. Esto facilita comparar visualmente cambios de SNR, modulacion, CP o numero de caminos. Para pruebas automatizadas, `run_image_transmission` tambien acepta `rng_seed`, lo que permite sobrescribir esa realizacion reproducible.

El numero de simbolos mostrado depende de la modulacion: QPSK agrupa 2 bits por simbolo, 16-QAM agrupa 4 y 64-QAM agrupa 6. Si la cantidad de bits no calza exactamente, el modulador agrega padding al final antes de generar los simbolos. El numero de bloques OFDM indica cuantas IFFT/bloques temporales fueron necesarios para transportar esos simbolos despues de reservar las subportadoras piloto.

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
- `controller/simulation_mgr.py`: coordina transmisor, canal, receptor, BER y PAPR.
- `core/config.py`: tablas de ancho de banda, prefijo ciclico y constelaciones.
- `core/utils.py`: conversion imagen/bits, scrambling y mapeo/demapeo digital.
- `core/ofdm_ops.py`: modulacion OFDM, prefijo ciclico, FFT/IFFT y ecualizacion.
- `core/channel.py`: canal AWGN y multipath con perfiles ITU y un perfil didactico discretizados.
- `tests/test_core.py`: pruebas de parametros, constelaciones, OFDM y smoke test del controlador.
- `PAPR.md`: explicacion tecnica del calculo de PAPR y CCDF.
- `FUENTES.md`: fuentes 3GPP/ETSI de los parametros LTE usados.

## Mejoras Tecnicas Aplicadas

- Constelaciones QPSK, 16-QAM y 64-QAM alineadas con el mapeo LTE.
- Mapeo/demapeo vectorizado con NumPy y cache de constelaciones.
- Subportadoras OFDM distribuidas alrededor de DC, dejando DC vacia.
- Prefijo ciclico normal variable por simbolo de slot.
- FFT de 15 MHz corregida a 1536.
- Perfil por defecto `ITU Vehicular B`, discretizado con `Fs = NFFT * Delta_f` y potencia media del PDP normalizada.
- Perfil `Didactico CP`, no ITU, disponible en `core/channel.py` para pruebas controladas del efecto CP: usa un camino directo y un eco a `12 us`.
- Slider de caminos alineado al perfil activo por defecto; la interfaz muestra retardos, ganancias, muestras discretas y margen de CP.
- Pilotos QPSK deterministas cada 6 subportadoras activas, con patron escalonado 0/3 entre bloques y estimacion DFT/LS regularizada. Esta aproximacion conserva una separacion base tipo CRS y evita que la estimacion de canal tape el efecto didactico del CP.
- Aviso de margen CP/retardo para detectar posibles condiciones de ISI.
- Curva BER multi-modulacion con Monte Carlo sobre la imagen cargada e intervalos de confianza al 95%.
- PAPR sobremuestreado con `L=4` y documentacion tecnica en `PAPR.md`.
- Worker thread para transmision, BER y PAPR, evitando que la ventana se congele mientras calcula.
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
- La estimacion de canal por pilotos esta simplificada: el canal se considera estatico durante cada transmision y se estima con LS regularizado en dominio temporal.
- El canal Rayleigh usa taps estaticos durante cada transmision o corrida; no modela aun variacion temporal Jakes/Doppler.
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
