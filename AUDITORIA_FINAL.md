# Auditoria final del simulador

Este documento resume la revision final del proyecto en su estado presentable.
El objetivo no es describir cada linea de codigo, sino dejar claro que partes
son coherentes con LTE-OFDM, que decisiones son simplificaciones didacticas y
que limitaciones conviene mencionar durante la presentacion.

## Estado general

El proyecto implementa una cadena LTE-OFDM educativa para transmitir una imagen
en escala de grises:

```text
imagen -> bits -> scrambling -> QPSK/16-QAM/64-QAM -> OFDM con pilotos
       -> CP -> canal Rayleigh + AWGN -> quitar CP -> FFT
       -> estimacion de canal -> ecualizacion -> bits -> imagen recibida
```

La version actual es coherente para una practica de comunicaciones moviles:
usa numerologia LTE simplificada, subportadoras activas alrededor de DC,
prefijo ciclico, pilotos conocidos, estimacion de canal, BER Monte Carlo y
PAPR empirico.

## Puntos tecnicamente correctos

- Los anchos de banda LTE implementados son 1.4, 3, 5, 10, 15 y 20 MHz.
- Las subportadoras activas corresponden a `12 * RB`.
- La separacion de subportadoras es `15 kHz`.
- Los tamanos FFT siguen la relacion LTE usada por el simulador:
  `128, 256, 512, 1024, 1536, 2048`.
- El caso de 15 MHz usa FFT 1536, coherente con la tasa LTE-like de 23.04 Msps.
- El bin DC se deja vacio.
- Las subportadoras activas se mapean usando la convencion real de `numpy.fft`:
  frecuencias negativas al final del vector y positivas despues de DC.
- El CP normal usa un primer simbolo mas largo y seis posteriores mas cortos,
  escalados desde la referencia de FFT 2048.
- El CP extendido usa seis simbolos con CP constante.
- QPSK, 16-QAM y 64-QAM usan constelaciones normalizadas.
- La estimacion de canal se hace con pilotos conocidos y ecualizacion por
  subportadora.
- El canal usa por defecto el perfil no ITU `Didactico CP`, con un eco a
  `12 us` elegido para quedar fuera del CP normal y dentro del CP extendido.
- Los perfiles ITU Pedestrian/Vehicular siguen disponibles para pruebas mas
  realistas y se discretizan segun `Fs = NFFT * Delta_f`.
- El ruido AWGN se referencia a la potencia transmitida, por lo que las
  atenuaciones del canal afectan la SNR recibida.
- La transmision manual usa una semilla fija por defecto para que la misma
  configuracion produzca la misma realizacion de canal y ruido.
- El resumen de transmision muestra BER, bits totales de la imagen, simbolos
  modulados, bloques OFDM requeridos y subportadoras activas.
- La curva BER usa la imagen cargada como carga util y compara QPSK, 16-QAM y
  64-QAM simultaneamente.
- La BER incluye intervalo de confianza al 95%, corridas Monte Carlo por punto
  y la configuracion fisica usada: ancho de banda, subportadoras activas,
  prefijo ciclico, perfil de canal activo y caminos multipath.
- La curva PAPR compara las tres modulaciones y usa sobremuestreo `L=4`.
- El resumen de PAPR reporta ancho de banda, subportadoras activas y bloques
  OFDM evaluados; CP/canal no aplican porque se mide antes de ambos.
- Las simulaciones pesadas corren en un worker thread para que la interfaz no
  se bloquee mientras calcula.

## Decisiones didacticas

Estas partes son simplificaciones conscientes y conviene explicarlas como tal:

- No se implementa LTE completo, sino una cadena OFDM inspirada en LTE.
- No hay codificacion de canal, interleaving, HARQ ni planificador.
- No hay tramas/subtramas LTE completas ni canales fisicos PDCCH/PDSCH reales.
- Los pilotos son una simplificacion inspirada en CRS: se colocan en todos los
  simbolos OFDM. La separacion CRS LTE de referencia es 6 subportadoras, pero
  el simulador usa 2 para que la estimacion de canal no tape el efecto
  didactico del CP.
- El receptor asume sincronizacion perfecta.
- No se modela CFO, error de temporizacion, ruido de fase ni no linealidad RF.
- El canal Rayleigh es estatico durante cada transmision/corrida; no incluye
  Doppler/Jakes.
- La imagen se procesa como escala de grises de `250x250`.
- PAPR se mide antes del canal y antes del CP, sobre el simbolo OFDM util.

## Riesgos revisados

- **FFT y DC:** se evito el error comun de poner DC en `N/2` sin `ifftshift`.
  El proyecto usa indices compatibles con `numpy.fft`.
- **BER con bits aleatorios:** la BER ya no usa carga util aleatoria; parte de
  los bits reales de la imagen.
- **PAPR Monte Carlo:** PAPR ya no usa Monte Carlo porque se busca la CCDF
  empirica de la imagen cargada.
- **Reproducibilidad visual:** la transmision manual fija la semilla del canal y
  ruido por defecto. Esto permite repetir una configuracion y observar mejor el
  efecto de cambiar SNR, modulacion, CP o caminos.
- **Interfaz bloqueada:** BER y PAPR se ejecutan fuera del hilo principal de la
  GUI.

## Validacion de cierre

En la revision final se ejecutaron estos comandos desde la raiz del proyecto:

```bash
venv/bin/python -m compileall main.py controller core ui tests
venv/bin/python -m unittest discover -v
```

Tambien se probo la ventana con una imagen reducida para verificar que
transmision, BER y PAPR completan correctamente desde el worker thread.

Antes de presentar, es recomendable abrir la aplicacion con una imagen real y
probar visualmente:

```text
1. TRANSMITIR IMAGEN
2. GENERAR CURVA BER
3. ANALIZAR PAPR
```

## Veredicto

La version actual esta en condiciones presentables para una practica academica
de LTE-OFDM. Lo mas importante para defenderla es explicar que el proyecto no
pretende ser una pila LTE completa, sino un simulador de capa fisica OFDM con
parametros LTE, canal multipath didactico/ITU, pilotos, BER y PAPR.
