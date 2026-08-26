# Laboratorio

Scripts que se ejecutan **a mano**, no desde la UI. Son los procesos que necesitan
criterio en cada paso: mirar el resultado, decidir un umbral, elegir qué conservar.

Lo que sí se podía automatizar está en la sección **Estabilización avanzada**
(`converter/avanzada.py`). Esto es el resto: el trabajo que hubo alrededor y que
tiene valor conservar aunque no quepa en un botón.

> **No son herramientas llave en mano.** Casi todos llevan rutas y constantes del
> material concreto para el que se escribieron (eclipse del 12/08/2026, dos cámaras
> Sony). Sirven como punto de partida y como registro de *cómo* se resolvió cada
> problema, no para lanzarlos tal cual sobre otro material.

Para entender el porqué de cada decisión: **[BITACORA.md](BITACORA.md)**.

## Requisitos

```bash
pip install numpy pillow          # todos
pip install tensorflow==2.16.2    # solo interpolacion/
```
Más `ffmpeg` y `exiftool`, que la app ya exige.

---

## deteccion/ — encontrar el objeto y medir su calidad

| Script | Qué hace |
|---|---|
| `detect.py` | **El más reutilizable.** Ajuste de circunferencia al limbo, con la distinción entre limbo solar y lunar. Módulo, no ejecutable |
| `vnitidez.py` | Nitidez como anchura de transición del borde (20 %→80 %) |
| `fases.py` | Separa fase parcial de totalidad comparando el brillo dentro y fuera del limbo |
| `calidad.py` | Nitidez y sobreexposición de una tanda entera |

`detect.py` es el corazón de todo. Contiene tres estrategias encadenadas: Hough de
radio fijo para enganchar desde cero, ajuste al limbo solar exigiendo fotosfera por
dentro, y ajuste genérico por máximo gradiente radial para la totalidad.

## fotos/ — tratamiento de una tanda de fotografías

| Script | Qué hace |
|---|---|
| `analyze.py` | Primer barrido: brillo, tamaño y posición del objeto en cada foto |
| `run_detect.py` | Detección fina sobre toda la tanda, guarda `centers.json` |
| `crop.py` | Recorte cuadrado centrado, con relleno o descarte si no cabe |
| `finalize.py` | Aparta las inservibles y genera el CSV de control |
| `reorg.py` | Reparte por nivel de exposición en subcarpetas |
| `horquillas.py` | **Reconstruye las horquillas** y ordena por EV = log2(t·ISO/f²) |
| `brillo.py` | Brillo del sujeto, no del cuadro |
| `secuencias.py` | Selección con programación dinámica: reparto temporal + continuidad de luz |
| `secuencia_anillo.py` | Recentrado iterativo desde el original |

## video/ — extracción y reducción

| Script | Qué hace |
|---|---|
| `pase1.py` | Mide los ~10.000 fotogramas por tubería |
| `selecciona3a1.py` | Agrupa 3:1 y ordena candidatos por calidad |
| `pase2.py` | Elige, centra, recorta y escribe ProRes en una pasada |
| `pase3_png.py` | Exporta la misma selección como PNG desde el original |
| `busca_estables.py` | Busca sustitutos en una ventana problemática |
| `rehacer_ocultacion.py` | Muestreo con aceleración decreciente (frena al final) |
| `video_extrae.py` | Extracción por lista de instantes |

## estabilizacion/ — las cuatro versiones, en orden

Vale la pena leerlas en orden: **cada una arregla el fallo de la anterior**.

| Script | Método | Resultado |
|---|---|---|
| `puesta_mide.py` | Solo mide el recorrido | Diagnóstico |
| `puesta_estabiliza.py` | Ventana de suavizado | 6,3 → 4,0 px |
| `puesta_bloquea.py` | Bloqueo total, trayectoria integrada | 0,0 px de mediana… pero **deriva 133 px** |
| `puesta_v2.py` | Anclas encadenadas | Deriva plana ~53 px |
| `puesta_v3.py` | **Anclas + descarte de medidas malas + recorte del clip** | **2–4 px** |

`puesta_v3.py` es el bueno y su método está portado a `converter/avanzada.py`.

## interpolacion/ — FILM (fuera de la UI)

| Script | Qué hace |
|---|---|
| `film_prueba.py` | Prueba entre dos claves, interpolación recursiva |
| `film_prueba_v2.py` | Variante con normalización de exposición |
| `film_secuencia.py` | Secuencia completa con densidad variable por hueco |

Modelo: `akhaliq/frame-interpolation-film-style` en Hugging Face (SavedModel, 148 MB).
~24 s por fotograma a 1280² sin GPU.

**Conclusión de haberlo probado:** funciona muy bien en huecos de 1–3 s y se rompe en
los largos, donde tiene que inventar geometría que nadie fotografió. La normalización
de exposición (v2) mejora los grumos pero estropea las zonas tenues, porque el cambio
de brillo no es uniforme por el cuadro. Ver la bitácora.

## montaje/

`z3_monta.py` — secuencia de imágenes con duración y encadenado **por archivo**,
unificando tamaños al techo que no obliga a ampliar ninguna.

## verificacion/

| Script | Qué hace |
|---|---|
| `audita3a1.py` | Audita la secuencia final: negros, movidos, descentrado |
| `audit.py` | Descentrado sobre los recortes ya generados |
| `check_out.py` | Hoja de contacto con retícula |
| `verify.py` | Dibuja el círculo ajustado sobre el original — para ver si el ajuste acierta |
| `sheets.py` | Hojas de contacto con realce gamma para material oscuro |

`verify.py` es el que más veces salvó el trabajo: pinta el círculo detectado encima de
la imagen. Casi todos los fallos de detección se vieron ahí antes que en ningún número.

## whatsapp/

| Script | Qué hace |
|---|---|
| `descifra.py` | Descifra `msgstore.db.crypt15` con la clave de 64 dígitos y resume qué hay dentro |

Lo normal es hacerlo desde la app (sección **WhatsApp**), que además descarga la copia
del móvil. Esto queda para cuando interesa una terminal: probar otra copia, un fichero
traído a mano, o automatizarlo. La lógica vive en `whatsapp/backup.py`; el script solo
pide la clave sin hacer eco de ella.
