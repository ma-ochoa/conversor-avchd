# Estabilización avanzada

Sección independiente con los procesos que la estabilización normal (vid.stab) no
cubre. No sustituye a nada: convive con `/estabilizacion` y resuelve otros casos.

**Diferencia de fondo con vid.stab:** vid.stab *suaviza* la trayectoria de la cámara
para que el movimiento resulte fluido. Aquí se hace lo contrario cuando hace falta —
*eliminarla* del todo, para que el encuadre quede fijo como con trípode — y además se
puede seguir un objeto concreto en vez del fondo.

---

## Archivos

| Archivo | Qué contiene |
|---|---|
| `converter/avanzada.py` | Los procesos. Funciones puras sobre numpy |
| `converter/avanzada_jobs.py` | Trabajos en segundo plano (mismo patrón que `stabilize_jobs`) |
| `templates/avanzada.html` | La página |
| `static/avanzada.js` | Front-end |

Añadido a archivos existentes, sin tocar nada más:
- `app.py`: tres rutas (`/avanzada`, `/api/avanzada`, `/api/avanzada-status/<job_id>`) e imports
- `templates/_base.html`: un enlace en el menú lateral
- `requirements.txt`: `numpy` y `Pillow`

## Dependencias

`numpy` y `Pillow`, además de ffmpeg/ffprobe que ya usa la app. Si faltan, se lanza
`DepsMissingError` con el comando de instalación, igual que hace `ToolsMissingError`
con ffmpeg. La app arranca igual sin ellas; solo falla esta sección.

## Salida

Todo va a `avanzada/<proceso>/` dentro de la carpeta de trabajo, resuelta con
`config.resolve_output_base()` — la misma que usan `conversion/`, `estabilizado/`,
`recompresion/` y `montaje/`. El original nunca se toca. La salida hereda la fecha de
captura del original para que no se pierda el orden cronológico.

---

## Los cuatro procesos

### 1. Bloqueo de encuadre

`estabilizar_bloqueo(source, dest, modo, suavizado_seg, anclas_seg, calidad_min, ...)`

Corrige el recorrido completo de la cámara moviendo el **origen del recorte**, no
remuestreando: cada píxel de salida es un píxel original.

Dos modos:
- **Bloqueo total** — corrige todo el recorrido. El encuadre queda fijo.
- **Suavizado** — corrige solo la desviación respecto a la trayectoria suave, así que
  respeta el movimiento lento intencionado.

**Cómo se mide el recorrido, y por qué así.** Es la parte que más costó acertar:

- *Sumar el desplazamiento fotograma a fotograma* acumula el error de cada medida. Con
  1.313 fotogramas y 1–2 px de error por medida, la trayectoria se desvía más de 120 px
  y el encuadre vuelve a moverse a mitad del clip.
- *Medir todo contra el primer fotograma* no acumula, pero falla cuando la escena
  cambia: en un atardecer, la calidad del pico de correlación cae de 220 a 9 y las
  medidas se vuelven basura.
- **Anclas cada N segundos** — las anclas se encadenan entre sí (una decena de sumas) y
  cada fotograma se mide contra su ancla, que está cerca y se le parece. El error
  acumulado baja de ~120 px a ~20.

Medido sobre material real (52 s a pulso, 300 mm):

| | Original | Suavizado 1 s | Bloqueo total |
|---|---|---|---|
| Temblor mediano | 6,3 px | 4,0 px | **0,0 px** |
| p95 | 28,6 px | 13,1 px | 8,2 px |

**Límite conocido:** el rolling shutter no se corrige por traslación. Los fotogramas con
sacudidas bruscas quedan internamente deformados y eso es irreducible por este método.

### 2. Seguir objeto

`seguir_objeto(source, dest, radio, lado, ...)` y `ajustar_disco(a, cx, cy, R)`

Recorta un cuadrado centrado en un objeto circular, fotograma a fotograma. Ajusta una
circunferencia de **radio fijo** al borde del objeto: lanza rayos desde el centro
estimado y busca en cada uno el punto de mayor gradiente radial.

Con el radio fijado (y no libre) el ajuste es estable aunque solo se vea un arco del
objeto — el caso de un disco tapado a medias o cortado por el encuadre.

El radio se puede dar en píxeles o calcular con `radio_px(focal_mm, sensor_mm,
ancho_px, objeto)` a partir de la óptica.

**Detalles que importan:**
- El centro se sigue desde el fotograma anterior. Arrancar del centroide de brillo no
  converge: en un creciente el centroide cae en el cuerno, a decenas de píxeles del
  centro real, y desde ahí los puntos del limbo se salen de la banda de búsqueda.
- Cuando el ajuste falla (señal débil, objeto tapado) se **extrapola** de la deriva
  reciente en vez de descartar el fotograma. En un plano fijo esa deriva es lineal y
  limpia.

### 3. Extraer fotogramas

`extraer_fotogramas(source, dest_dir, ratio, descartar_negros, descartar_movidos, ...)`

Reducción N:1 quedándose con el **mejor** fotograma de cada grupo, no con uno fijo. Con
3:1 hay tres candidatos por hueco, así que en los momentos malos casi siempre queda
alguno aprovechable.

Dos filtros:
- **Caídas a negro** del propio vídeo, por el máximo del fotograma.
- **Movidos**, por la relación píxeles-en-transición / píxeles-de-núcleo.

**El umbral de nitidez es relativo, no absoluto.** Un umbral fijo no vale: en material
que cambia de contraste el indicador sube o baja por sí solo. Sobre material real, un
fotograma nítido daba 0,19 al principio del clip y 2,13 al final — y los dos eran
buenos. Se compara con la **mediana local** (ventana de ~100 fotogramas), que es lo que
separa la movida real de la evolución natural de la escena.

### 4. Verificación

`hoja_contacto(origen, dest, ...)` y `auditar(origen, radio)`

- **Hoja de contacto**: miniaturas en cuadrícula con retícula central. Acepta carpeta de
  imágenes o vídeo.
- **Auditar**: vuelve a medir **sobre el resultado**, no sobre los cálculos intermedios.
  Devuelve temblor entre consecutivos, desvío respecto al primer fotograma y, si se le
  da el radio, descentrado del objeto.

Esto no es un extra: es lo que descubre los fallos de verdad. Sobre material real
detectó 21 fotogramas movidos que se habían colado pese al filtro, y una deriva que
reaparecía a partir del segundo 25 y que los datos intermedios daban por buena.

---

## Contrato de las funciones

Todas las de proceso aceptan `progress_cb(fraccion, fase="")` y devuelven un `dict` de
estadísticas que la UI pinta en la columna «Resultado».

```python
probe_video(source)                    -> {width, height, fps, frames, duration}
medir_fotogramas(source, cb, deint)    -> [{n, mx, media, cx, cy, borde}, ...]
clasificar(medidas, ...)               -> añade {rel, veredicto: ok|negro|movido}
agrupar_pulldown(medidas, ratio)       -> [[mejor, ...], ...]  ordenado por calidad
extraer_fotogramas(...)                -> {escritos, grupos_omitidos, negros_detectados, ...}
medir_trayectoria(source, anclas_seg)  -> {px, py, calidad, fotogramas, info}
estabilizar_bloqueo(...)               -> {recorte, porcentaje_imagen, recorrido_px, ...}
radio_px(focal_mm, sensor_mm, ancho)   -> float
ajustar_disco(a, cx, cy, R)            -> (cx, cy, n_puntos)
seguir_objeto(...)                     -> {fotogramas, lado, seguidos, extrapolados}
hoja_contacto(...)                     -> {miniaturas, destino}
auditar(origen, radio)                 -> {temblor_consecutivo, desvio_vs_primero, ...}
```

---

## Lo que NO está aquí, y por qué

Estos procesos existieron en el trabajo del que salió esta sección, pero necesitan
criterio humano y no se automatizan en un botón:

| | Por qué |
|---|---|
| Distinguir dos bordes del mismo objeto | Un creciente tiene dos arcos fuertes. Elegir el correcto exige saber qué hay a cada lado |
| Clasificar la fase del fenómeno | Cambia qué borde seguir y qué umbrales valen |
| Separar qué tomas son del objeto | Requiere mirarlas |
| Elegir la narrativa del montaje | Qué tomas, en qué orden, con qué ritmo |
| Diagnosticar por qué falla algo | Los tres fallos de fondo (centroide desviado, ganancia global que estropea otra zona, deriva acumulada) se encontraron mirando resultados y razonando |
| Ajustar umbrales caso por caso | Los valores por defecto salieron de medir *un* material concreto |

También quedó fuera la **interpolación de fotogramas con FILM** (red de Google): el
código funciona, pero exige TensorFlow y un modelo de 148 MB, tarda ~24 s por fotograma
sin GPU, y solo da buen resultado en huecos cortos. Como dependencia pesada para un uso
puntual, no compensa meterla aquí.

Y el **montaje de secuencias de imágenes con encadenados** no está porque la sección
`/montaje` ya cubre ese terreno; lo que faltaría es admitir secuencias de imágenes
además de clips.
