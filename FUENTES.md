# Fuentes LTE usadas en el simulador

Este archivo resume de donde salen los parametros LTE usados en el proyecto. La idea es distinguir entre datos tomados de especificaciones 3GPP/ETSI y decisiones propias del simulador.

## Fuentes principales

| Dato usado en el simulador | Fuente |
| --- | --- |
| Anchos de canal LTE: 1.4, 3, 5, 10, 15 y 20 MHz | ETSI TS 136 104 / 3GPP TS 36.104, seccion 5.6, tabla 5.6-1. |
| Configuracion de resource blocks por ancho de canal: 6, 15, 25, 50, 75 y 100 RB | ETSI TS 136 104 / 3GPP TS 36.104, seccion 5.6, tabla 5.6-1. |
| Un resource block LTE ocupa 12 subportadoras y, con 15 kHz, equivale a 180 kHz en frecuencia | ETSI TS 136 211 / 3GPP TS 36.211, seccion 6.2.3, tabla 6.2.3-1. |
| Espaciamiento normal de subportadoras en LTE: 15 kHz | ETSI TS 136 211 / 3GPP TS 36.211, secciones 6.2.3 y 6.12. |
| Casos especiales con otros espaciamientos, como 7.5 kHz en MBSFN/MBMS | ETSI TS 136 211 / 3GPP TS 36.211, secciones 6.2.3, 6.10.2 y 6.12. |
| Longitudes de prefijo ciclico normal: 160 muestras para el primer simbolo y 144 para los siguientes, referidas a N=2048 y 15 kHz | ETSI TS 136 211 / 3GPP TS 36.211, seccion 6.12, tabla 6.12-1. |
| Longitud de prefijo ciclico extendido: 512 muestras para 15 kHz, referida a N=2048 | ETSI TS 136 211 / 3GPP TS 36.211, seccion 6.12, tabla 6.12-1. |
| Tamanos FFT usados para 15 kHz y anchos 1.4/3/5/10/15/20 MHz: 128, 256, 512, 1024, 1536, 2048 | ETSI TS 136 104 / 3GPP TS 36.104, anexo E.5.1, tablas de ventana EVM para 15 kHz. |
| DC no transmitida en downlink | ETSI TS 136 104 / 3GPP TS 36.104, seccion 5.6, figura 5.6-2; tambien consistente con la generacion OFDM de TS 36.211. |
| Mapeo QPSK | ETSI TS 136 211 / 3GPP TS 36.211, seccion 7.1.2, tabla 7.1.2-1. |
| Mapeo 16-QAM | ETSI TS 136 211 / 3GPP TS 36.211, seccion 7.1.3, tabla 7.1.3-1. |
| Mapeo 64-QAM | ETSI TS 136 211 / 3GPP TS 36.211, seccion 7.1.4, tabla 7.1.4-1. |
| Generacion OFDM baseband y uso de N=2048 para 15 kHz como referencia temporal | ETSI TS 136 211 / 3GPP TS 36.211, secciones 4 y 6.12. |
| Pilotos de referencia LTE espaciados cada 6 subportadoras en los simbolos CRS | ETSI TS 136 211 / 3GPP TS 36.211, seccion 6.10.1, especialmente el mapeo `k = 6m + ...`. |
| Perfiles Rayleigh ITU Pedestrian A/B y Vehicular A/B: retardos relativos y potencias medias por tap | ITU-R M.1225, seccion 1.2.2 y tablas de tapped-delay-line; valores portados localmente desde `practica1/itu_profiles.py`. |

## Enlaces

- ETSI TS 136 104 V18.6.0: LTE; E-UTRA; Base Station radio transmission and reception.  
  https://www.etsi.org/deliver/etsi_ts/136100_136199/136104/18.06.00_60/ts_136104v180600p.pdf

- ETSI TS 136 211 V17.1.0: LTE; E-UTRA; Physical channels and modulation.  
  https://www.etsi.org/deliver/etsi_ts/136200_136299/136211/17.01.00_60/ts_136211v170100p.pdf

- Portal 3GPP para TS 36.104.  
  https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=2412

- Portal 3GPP para TS 36.211.  
  https://portal.3gpp.org/desktopmodules/Specifications/SpecificationDetails.aspx?specificationId=2425

- ITU-R M.1225: Guidelines for evaluation of radio transmission technologies for IMT-2000.  
  https://www.itu.int/dms_pubrec/itu-r/rec/m/R-REC-M.1225-0-199702-I!!PDF-E.pdf

## Decisiones del simulador que no salen directamente de LTE

Estas partes son elecciones de modelado para mantener el simulador didactico y ligero:

- Transmitir una imagen en escala de grises como flujo de bits.
- Redimensionar la imagen a `250x250`.
- Usar scrambling XOR con semilla local.
- Usar `Didactico CP` como perfil activo por defecto: no es ITU, sino un canal determinista de dos caminos con eco a `12 us`, creado para mostrar el efecto del CP normal frente al CP extendido.
- Mantener perfiles ITU Pedestrian/Vehicular discretizados como alternativas de canal mas realistas.
- Asumir sincronizacion perfecta.
- Usar Monte Carlo para BER con un numero configurable de corridas.
- Usar factor de sobremuestreo `L=4` para estimar PAPR.
- Simplificar los CRS LTE a pilotos QPSK deterministas en todos los simbolos OFDM. La separacion CRS LTE de referencia es de 6 subportadoras; la separacion actual del simulador es de 2 subportadoras para que la estimacion de canal no tape el efecto didactico del CP con el perfil `Didactico CP`.
- Mantener el canal Rayleigh estatico por corrida, sin variacion temporal Doppler/Jakes.

## Nota sobre espaciamiento entre subportadoras

En LTE convencional el espaciamiento de subportadoras usado por este simulador es `15 kHz`. La especificacion contempla otros espaciamientos en escenarios especiales como MBSFN/MBMS, pero no son una numerologia flexible general como en 5G NR. Por eso el simulador mantiene `delta_f = 15 kHz` fijo para la operacion LTE-OFDM base.
