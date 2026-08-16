# Estado del proyecto — documento de continuidad

> Este documento existe para que una sesión futura (humana o de Claude Code) pueda
> retomar el desarrollo leyendo **solo esto**, sin necesitar el historial de la
> conversación anterior. Complementa a `README.md` (que es de cara al usuario); este
> documento es técnico y explica el *por qué* de las decisiones, no solo el *qué*.
>
> Última actualización: sesión que añadió el **historial de ajustes de
> estabilización** — borrador por clip (guardar/probar/descartar) independiente de
> renderizar, marcado de clips analizados/ajustados en el escaneo, y visibilidad
> cruzada entre Estabilización y Montaje sin recomprimir. Repo:
> https://github.com/ma-ochoa/conversor-avchd — rama `main`. Comprueba
> `git log --oneline -5` y `git status` al empezar para confirmar que sigue así.

## Qué es esto

App de escritorio (Flask local + navegador, sin build step, sin frontend framework —
HTML/CSS/JS planos) para el flujo de trabajo de vídeo de una cámara Sony (AVCHD 1080i y
XAVC-S 4K) y otras fuentes MP4/MOV: importar → renombrar por fecha → remuxear sin
pérdida → estabilizar temblor → montar (recortar, titular, transiciones) → exportar.
Todo pensado para que el resultado se vea bien en Synology Photos / Plex / Emby / TV.

El usuario (Miguel) no es necesariamente el que picotea código — a menudo pide que se
implemente todo de forma autónoma, se pruebe con sus clips reales, y se le dé un
resumen al final. Ese es el patrón de trabajo esperado: **construir, probar con
material real (no asumir), y documentar antes de resumir**.

## Estado: todo lo pedido hasta ahora está implementado, probado y publicado

No hay ninguna tarea a medias. Lo único explícitamente aplazado es la "fase 2" (ver
más abajo). Si en la próxima sesión el usuario no pide nada nuevo concreto, no hay
"trabajo pendiente" que retomar de oficio — este documento es para dar contexto, no
una lista de TODOs sin terminar.

## Arquitectura

- **Backend**: Flask (`app.py`), un solo proceso, `debug=False`. Puerto **5050** fijo
  (hardcoded en `app.py` y en `Iniciar Conversor AVCHD.command`).
- **Frontend**: HTML/CSS/JS servidos por Flask (`templates/`, `static/`), sin build,
  sin framework, sin dependencias npm. **4 páginas** compartiendo un layout base con
  barra lateral (`templates/_base.html`, `{% extends %}`): `/` (Conversión),
  `/recompresion`, `/estabilizacion`, `/montaje`. Cada página tiene su propio JS
  independiente (nada de SPA/router — son recargas de página normales; la barra
  lateral es visualmente persistente porque el layout es idéntico en las 4, no porque
  no haya recarga). `static/shell.js` (cargado en todas) recuerda en `localStorage` la
  última carpeta de proyecto usada y precarga el campo `#path-input` de la página que
  sea — ver "Hallazgos" sobre el orden de ejecución de scripts que esto exige.
- **Procesamiento de vídeo**: siempre `ffmpeg`/`ffprobe` vía `subprocess`, nunca
  librerías Python de vídeo. Hay DOS binarios de ffmpeg relevantes:
  - `ffmpeg` (Homebrew normal) — usado para remuxeo/miniaturas/proxies. No tiene
    `libvidstab` ni `libfreetype`.
  - `ffmpeg-full` (Homebrew, instalado aparte, keg-only, resuelto por
    `converter/stabilize.py::find_ffmpeg_with_vidstab()` buscando en
    `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg`) — necesario para `vidstabdetect`/
    `vidstabtransform` (estabilización) y `drawtext`/`libass` (títulos del montaje).
    **Todo lo relacionado con estabilización y con el montaje usa `ffmpeg-full`.**
- **Trabajos largos** (convertir, estabilizar, exportar montaje, analizar
  estabilización): hilos Python en segundo plano (`threading.Thread`, `daemon=True`)
  con un diccionario en memoria `_jobs` por módulo, y el frontend hace polling a un
  endpoint `*-status/<job_id>` cada ~800ms. No hay cola persistente ni Redis ni nada
  parecido — si se reinicia el servidor, los jobs en memoria se pierden (pero los
  ficheros que ya se escribieron en disco quedan bien, y el `.manifest.json`/caché en
  disco permite retomar sin recalcular lo ya hecho).
- **Sin base de datos**: todo el estado persistente vive en el sistema de ficheros,
  dentro de la propia carpeta que el usuario está procesando (ver más abajo).

## Mapa de archivos

```
app.py                          Todas las rutas Flask (una sola app, sin blueprints)

templates/_base.html            ⭐ Layout compartido: barra lateral + bloques Jinja
templates/index.html            Página de Conversión ({% extends "_base.html" %})
templates/recompresion.html     Página de Recompresión
templates/estabilizacion.html   Página de Estabilización
templates/montaje.html          Página de Montaje (editor)

static/shell.js                 Recuerda la carpeta de proyecto entre módulos (localStorage)
static/conversion.js            JS de Conversión
static/recompresion.js          JS de Recompresión
static/estabilizacion.js        JS de Estabilización (tabla + modal "Analizar y ajustar")
static/stabilize_preview.js     ⭐ Preview de estabilización en canvas — compartido entre
                                 Estabilización y Montaje (ver detalle abajo)
static/montaje.js               JS del editor — usa stabilize_preview.js para su propio modal
static/style.css                Estilos compartidos + layout de la barra lateral
static/montaje.css              Estilos del editor, reutilizados también por Estabilización
                                 (modal/canvas) — cargado desde ambas plantillas

converter/
  ffmpeg_ops.py                 Remuxeo sin pérdida (remux_clip), FFMPEG_BIN="ffmpeg"
  metadata.py                   Fecha de captura vía exiftool (DateTimeOriginal, etc.)
  naming.py                     Nombres AAAAMMDD_HHMMSS.ext con desambiguación
  manifest.py                   .manifest.json genérico (qué ya se procesó, por carpeta)
  scanner.py                    Escaneo recursivo: vídeos/fotos/otros formatos, marca
                                 has_analysis/stabilize_draft por clip de vídeo
  jobs.py                       Job de "Convertir" (remuxeo + fotos)
  fonts.py                      Fuentes del sistema macOS para drawtext
  thumbnails.py                 Miniaturas .jpg cacheadas (carpeta .miniaturas/)
  project.py                    Guardar/cargar proyectos de montaje (JSON)
  montaje_clips.py              Lista de clips disponibles para montar/recomprimir,
                                 con el borrador de estabilización enlazado por origen

  stabilize.py                  ⭐ Núcleo de estabilización — ver detalle abajo
  stabilize_jobs.py             Job de "Estabilizar" (independiente) — usa el borrador
                                 guardado del clip si existe, si no los parámetros globales
  proxy.py                      Genera/cachea proxy ligero (.proxies/) para el canvas
  analyze_jobs.py               Job de "Analizar" (solo trayectoria) — genérico, lo usan
                                 tanto Montaje como el modal de Estabilización
  timeline_export.py            ⭐ Construye el filtro ffmpeg del montaje completo
  timeline_jobs.py              Job de "Exportar montaje"

  recompress.py                 Recompresión genérica (calidad CRF + tope de resolución)
  recompress_jobs.py            Job de "Recomprimir"
```

## `converter/stabilize.py` — cómo funciona de verdad

Es el módulo más importante y el que más ha costado afinar. Funciones clave:

- **`ensure_analysis(root, source, shakiness, accuracy)`**: pasada 1 de `vid.stab`
  (`vidstabdetect`). Cachea el `.trf` binario en `<root>/.vidstab_cache/<hash>.trf`,
  clave = `sha1(f"{source}|{shakiness}|{accuracy}")`, invalidada si cambia el tamaño
  del fichero origen. **Esto es lo lento** (en 4K, minutos u horas según duración —
  ver "Hallazgos" abajo). Devuelve también estadísticas (fotogramas de bajo contraste,
  confianza) parseadas del log de `vidstabdetect`, cacheadas junto al `.trf` en un
  `.json` hermano.
- **`stabilize_clip(source, dest, root, ..., shakiness, accuracy, smoothing, zoom_mode,
  zoom_percent)`**: pasada 2 (`vidstabtransform`) + codificación real a `dest`. Llama a
  `ensure_analysis` primero (con caché). Solo esta pasada 2 depende de
  `smoothing`/`zoom_mode`/`zoom_percent` — por eso cambiar esos parámetros y
  reprocesar es rápido (reutiliza el `.trf`), pero cambiar `shakiness`/`accuracy`
  invalida la caché y repite la pasada 1.
- **`get_preview_analysis(root, source, shakiness, accuracy)`**: para la vista previa
  del montaje. Llama a `ensure_analysis` (mismo caché, compartido con el botón
  "Estabilizar" independiente — analizar una vez sirve para ambos flujos) y además
  ejecuta `vidstabtransform` con `debug=1` para volcar la trayectoria de cámara
  fotograma a fotograma **sin codificar vídeo** (mucho más rápido que una pasada 2
  completa). Devuelve `{path: [{dx,dy,angle}, ...], fps, width, height, duration,
  stats}`. Esto también se cachea (`.path.json` hermano del `.trf`).
- `zoom_mode`: `"auto_static"` (`optzoom=1`, el de siempre), `"auto_dynamic"`
  (`optzoom=2`), `"manual"` (`optzoom=0:zoom=X`, control tipo Pinnacle).
- El filtro siempre empieza con `yadif=mode=1:deint=interlaced` — desentrelaza
  **solo si el fotograma viene marcado como entrelazado** (AVCHD 1080i), dejando
  intacto el vídeo progresivo (4K/MP4 de cámaras modernas). Así se pueden mezclar
  fuentes AVCHD y 4K en el mismo montaje sin lógica condicional por extensión.
- **`has_cached_analysis(root, source, shakiness, accuracy)`**: comprueba si el `.trf`
  de esos parámetros ya existe y es válido (tamaño de origen coincide), sin ejecutar
  ffmpeg. La usa `scanner.py` en cada clip del escaneo — por eso el escaneo no se
  vuelve más lento aunque haya cientos de clips.
- **`save_stabilize_draft` / `load_stabilize_draft` / `discard_stabilize_draft`**:
  el "borrador" de ajustes por clip — ver la sección siguiente.

## `converter/timeline_export.py` — el montaje completo en una pasada

Construye un único `filter_complex` de ffmpeg con N clips de entrada. Por cada clip:

1. Si el clip trae `stabilize: {...}` en su entrada del proyecto, se antepone
   `vidstabtransform` (reutilizando `ensure_analysis`) **sobre el clip completo**,
   antes de `trim`. Esto es importante: `vid.stab` necesita ver la misma secuencia de
   fotogramas que analizó, así que el recorte in/out se aplica *después* de
   estabilizar, no antes.
2. `scale` + `pad` a 1920x1080 (así clips 4K y 1080p conviven en el mismo timeline).
3. `drawtext`/`overlay` si tiene título.
4. Se encadenan con `xfade`/`acrossfade` (vídeo/audio) para las transiciones —
   matemática de offset acumulado ya validada con 2 y 3 clips.

Todo en **una sola invocación de ffmpeg** — no hay pasos intermedios ni ficheros
temporales por clip. Un clip nunca se recodifica dos veces (estabilizar y luego
volver a codificar al exportar): el análisis se cachea, la codificación real ocurre
una vez, en la exportación final.

## Vista previa de estabilización en canvas (`static/stabilize_preview.js`)

Extraída a un módulo compartido — la usan tanto el modal de estabilización del
Montaje (un clip de la línea de tiempo) como el modal "Analizar y ajustar" de la
página de Estabilización (un clip cualquiera del escaneo). Es un `<script>` más,
cargado antes de `montaje.js`/`estabilizacion.js` en sus respectivas plantillas —
sin bundler, comparten scope global como el resto de la app (ver `shell.js`).

Flujo completo:

1. **Analizar** (`POST /api/montaje/analyze` → `analyze_jobs.py` — el nombre de la
   ruta es histórico, la usa cualquier página, no solo Montaje): ejecuta
   `get_or_create_proxy` (ver `proxy.py`, copia ligera 640px de ancho, misma
   proporción/fps, en `<root>/.proxies/`) y `get_preview_analysis`. Devuelve la
   trayectoria bruta + ruta del proxy.
2. **En el navegador** (`createStabilizePreview({video, canvas, seek, playBtn,
   toggle})` → devuelve `{setupPreview, recomputeAndRender, renderFrame, stop, play,
   ...}`): con la trayectoria ya descargada, **todo lo demás es JavaScript puro, sin
   servidor**:
   - `computeCorrections(analysis, smoothingWindow)`: acumula la trayectoria bruta
     (con recorte de valores atípicos a 4× la mediana — ver "Hallazgos"), aplica una
     media móvil como suavizado, y calcula la corrección por fotograma.
   - `autoZoomPercent(...)`: aproxima cuánto zoom automático haría falta — **no es el
     cálculo real de `vid.stab`**, es una estimación proporcional al desplazamiento
     máximo detectado. Se documenta como aproximación tanto en el código como en el
     README.
   - `renderFrame()`: dibuja el proxy en un `<canvas>` aplicando la corrección
     calculada (transform 2D), sincronizado con un `<video>` oculto que reproduce el
     proxy.
   - Mover los sliders de suavizado/zoom → recalcula y redibuja al instante, cero
     llamadas de red.
3. **Guardar**: en Montaje, la configuración se adjunta al clip en memoria
   (`item.stabilize`) y viaja tal cual al JSON del proyecto y a la exportación final.
   En Estabilización, se persiste en disco como "borrador" (ver siguiente sección) —
   ambos caminos usan el mismo objeto `{shakiness, accuracy, smoothing, zoom_mode,
   zoom_percent}` y, en la exportación/estabilización real, el mismo cálculo real de
   `vid.stab` (no la aproximación de JS).

## Historial de ajustes de estabilización (borrador por clip, entre módulos)

Petición del usuario: poder analizar/ajustar un clip en Estabilización, guardar o
descartar esos ajustes, y que el resto de la app (el escaneo, Montaje) los vea sin
tener que rebuscar en carpetas ni recomprimir nada. Piezas:

- **Almacén** (`converter/stabilize.py::save_stabilize_draft` /
  `load_stabilize_draft` / `discard_stabilize_draft`): reutiliza
  `manifest.load_manifest`/`record_entry`/`remove_entry` con
  `subfolder=".vidstab_cache"` → escribe en `<root>/.vidstab_cache/.manifest.json`,
  clave = ruta absoluta del clip **original** (no del `.trf`, que vive en ficheros
  hermanos con nombre-hash en esa misma carpeta — no colisionan). Es independiente de
  si el clip se ha llegado a analizar o renderizar: solo guarda qué parámetros eligió
  el usuario la última vez, para poder probarlos/guardarlos/descartarlos.
- **Rutas**: `POST /api/stabilize-draft` (guarda) y `DELETE /api/stabilize-draft`
  (descarta), body `{root, path, shakiness?, accuracy?, smoothing?, zoom_mode?,
  zoom_percent?}`.
- **Escaneo** (`scanner.py`): cada clip de vídeo lleva `has_analysis` (¿existe un
  `.trf` válido para el shakiness/accuracy del borrador, o los de por defecto si no
  hay borrador?) y `stabilize_draft` (el borrador tal cual, o `null`). La tabla de
  Estabilización pinta con esto el estado: `—` / `🔍 analizado` / `🩹 ajustado`.
- **Página de Estabilización** (`estabilizacion.js`): botón "🔍 Analizar y ajustar"
  por fila abre el modal compartido, precargado con el borrador si existe. "Guardar
  ajuste"/"Descartar ajuste guardado" llaman a las rutas de arriba y actualizan la
  fila sin recargar toda la tabla. El botón masivo "Estabilizar marcados" sigue
  mandando unos parámetros globales al job, pero **`stabilize_jobs.py` ahora
  comprueba el borrador de cada clip y lo usa en vez de esos parámetros globales si
  existe** — sin ningún cambio en el frontend, es puramente un `load_stabilize_draft`
  antes de llamar a `stabilize_clip` en `_run_job`.
- **Montaje** (`montaje_clips.py` + `montaje.js`): `montaje_clips.py` invierte el
  `.manifest.json` de `conversion/`/`estabilizado/` (origen → nombre de salida) para,
  dado un fichero ya convertido/estabilizado, encontrar su clip original y adjuntarle
  `stabilize_draft` si lo tiene. La cuadrícula de clips pinta una insignia "🩹 ajuste
  de estabilización guardado" y, al arrastrar el clip a la línea de tiempo,
  `addClipToTimeline` copia ese borrador a `item.stabilize` automáticamente.
  **Importante — guarda de doble estabilización**: esto solo pasa si
  `clip.source === "convertido"` (el clip viene de `conversion/`, aún sin
  estabilizar). Un clip que ya viene de `estabilizado/` es un vídeo YA procesado con
  `vid.stab`; si se le aplicase además el borrador como `item.stabilize`, la
  exportación final le metería `vidstabtransform` una segunda vez encima de un vídeo
  que ya no tiembla — con resultados impredecibles. La insignia y la herencia se
  omiten a propósito para esos clips (el borrador puede seguir viéndose en la propia
  página de Estabilización, solo no se hereda en Montaje).

## Hallazgos técnicos importantes (para no repetir el trabajo de descubrirlos)

1. **`vid.stab` NO reescala los vectores de movimiento entre resoluciones distintas.**
   Comprobado empíricamente: analizar a 640px de ancho y aplicar la corrección al
   vídeo a resolución completa (1920px) dio un zoom calculado de 3.55%, cuando el
   real (analizando a resolución completa) es 9.48% — una infracorrección de ~2.7×,
   coherente con la proporción de escalado (3×). **Por esto el análisis (pasada 1)
   siempre debe ejecutarse sobre la resolución real del vídeo**, nunca sobre un proxy
   reducido — un "atajo" ahí daría una estabilización más débil de lo que parece, sin
   ningún aviso. Esto NO afecta a la vista previa en canvas porque ahí no se
   re-analiza nada a otra resolución: se reutiliza la trayectoria calculada sobre el
   original y se aplica como *porcentaje* del ancho/alto (independiente de la
   resolución de visualización), no en píxeles absolutos.
2. **Un fotograma aislado de bajo contraste puede disparar la estimación de zoom en
   JS.** Al implementar `autoZoomPercent`, un solo valor atípico en la trayectoria
   bruta desplazaba toda la suma acumulada y el zoom estimado se iba al tope (50%)
   cuando el real era ~9%. Solucionado recortando cada `dx`/`dy` a 4× la mediana
   absoluta antes de acumular (`computeCorrections`). Sigue siendo una aproximación,
   no el cálculo real — está documentado así a propósito.
3. **La estabilización en 4K es muy lenta** (pasada 1, block-matching): un clip de
   4:25 min a 3840×2160 tardó más de 4 horas de CPU en analizarse en el Mac de
   pruebas. No es proporcional al tamaño del fichero, sino a los píxeles por
   fotograma. El remuxeo (sin estabilizar) no tiene este problema — es solo copia de
   contenedor.
4. **Un `<video>` con `display:none` no se puede dibujar en `<canvas>` con
   `drawImage()` en Chrome** — no da ningún error, simplemente no pinta nada. Hay que
   mantenerlo con `visibility:hidden` + tamaño 0, o similar, nunca `display:none`, si
   se va a usar como fuente de `drawImage`.
5. **Bug real de despliegue (ya corregido)**: una edición insertó una función
   auxiliar (`_clamp`) entre un decorador `@app.route(...)` y la función que debía
   decorar — Flask acabó registrando la función auxiliar como manejador de la ruta,
   causando un 500 en cada petición. Se detectó probando el flujo real en el
   navegador, no solo el código en aislado — **por eso conviene probar siempre a
   través de la app real antes de dar algo por terminado**, no solo con llamadas
   directas a las funciones Python.
6. **PNG con transparencia real**: `color=c=X@0.0` en el filtro `lavfi` de ffmpeg NO
   garantiza alfa=0 fiable; hay que forzarlo con `format=rgba,colorchannelmixer=aa=0.0`
   antes de dibujar encima. Se comprobó con `ffmpeg ... -f rawvideo -pix_fmt rgba -`
   y `xxd` para verificar el byte de alfa antes de dar por bueno un PNG de prueba.
7. **`movie=...,loop=loop=-1:size=1` sin acotar duración puede colgar ffmpeg** al
   combinarlo con `xfade` en el mismo grafo — el stream de imagen en bucle tiene
   duración "infinita" internamente y descoloca la sincronización de `xfade`. Se
   arregla añadiendo `trim=duration=<duración del clip>` justo después del `loop`.
8. **VideoToolbox (`fast_hw`) da una mejora modesta, no proporcional**: ~2× más
   rápida la codificación, pero como el análisis (la parte lenta) no se acelera con
   hardware, el ahorro total del proceso completo es solo ~15%. Calidad ligeramente
   inferior (VMAF ≈96/100 frente a libx264 al mismo bitrate). Documentado así en la
   UI para que no se venda como "2× más rápido todo el proceso".
9. **`scale=W:-2` combinado con `force_original_aspect_ratio=decrease` puede dar una
   anchura impar** y romper `libx264` ("width not divisible by 2"). Si solo hace falta
   limitar por un lado (p. ej. "que no supere tal ancho, sin ampliar"), más sencillo y
   fiable comprobar la resolución de origen con `ffprobe` a mano y aplicar
   `scale=W:-2` sin `force_original_aspect_ratio` — ver `converter/recompress.py`.
10. **Orden de ejecución entre `shell.js` (recuerda la carpeta) y el script propio de
    cada página**: si `shell.js` espera a `DOMContentLoaded` para rellenar
    `#path-input`, ese evento llega **después** de que el script de la página (que se
    carga justo a continuación, también bloqueante) ya haya lanzado su primera llamada
    a `loadDirs()` con el valor por defecto — la carpeta recordada se ve en el campo,
    pero la carpeta que realmente se listó es la incorrecta. Solución: en `shell.js`,
    rellenar el campo de forma síncrona a nivel superior del script (sin esperar a
    ningún evento), ya que al estar los `<script>` al final del `<body>` el elemento
    `#path-input` ya existe en el DOM en ese punto.

## Carpetas ocultas que la app genera dentro de la carpeta del usuario

Todas relativas a la carpeta que el usuario escanea (el "root" de cada operación).
Todas están en `.gitignore` — nunca deben subirse al repo, contienen datos/vídeo del
usuario o caché regenerable:

| Carpeta | Contenido | Módulo |
|---|---|---|
| `conversion/` | Vídeos/fotos remuxeados | `jobs.py` |
| `estabilizado/` | Vídeos estabilizados (botón independiente) | `stabilize_jobs.py` |
| `recompresion/` | Vídeos recomprimidos (formato no soportado o reducción de tamaño) | `recompress_jobs.py` |
| `montaje/proyectos/*.json` | Proyectos de montaje guardados | `project.py` |
| `montaje/*_final.mp4` | Exportaciones finales del montaje | `timeline_jobs.py` |
| `.miniaturas/` | Miniaturas .jpg cacheadas | `thumbnails.py` |
| `.vidstab_cache/` | `.trf` + `.json` (stats) + `.path.json` (trayectoria) por clip, más `.manifest.json` (borrador de ajustes por clip, ver más arriba) | `stabilize.py` |
| `.proxies/` | Proxies ligeros (640px) para el canvas | `proxy.py` |

Ninguna de estas carpetas tiene límite de tamaño ni expiración — si en el futuro se
usa la app con muchos clips durante mucho tiempo, podría valer la pena añadir una
forma de purgar cachés antiguas. No implementado, no pedido todavía.

## Rutas Flask (API completa)

```
GET  /                              Página de Conversión
GET  /recompresion                  Página de Recompresión
GET  /estabilizacion                Página de Estabilización
GET  /montaje                       Página de Montaje (editor)
GET  /media?path=                   Sirve un fichero de vídeo/imagen (range requests)
GET  /api/browse?path=               Listar subcarpetas (navegador de carpetas propio)
POST /api/pick-folder                Selector nativo macOS (carpeta)
POST /api/pick-file                  Selector nativo macOS (imagen para título)
POST /api/scan                       Escanear carpeta (vídeos/fotos/otros) — lo usan
                                      Conversión, Estabilización y Recompresión
POST /api/convert                    Lanzar job de conversión
GET  /api/status/<job_id>            Progreso de conversión
POST /api/stabilize                  Lanzar job de estabilización (independiente;
                                      usa el borrador guardado de cada clip si existe)
GET  /api/stabilize-status/<job_id>  Progreso de estabilización
POST /api/stabilize-draft            Guardar el borrador de ajustes de un clip
DELETE /api/stabilize-draft          Descartar el borrador de ajustes de un clip
POST /api/recompress                 Lanzar job de recompresión
GET  /api/recompress-status/<job_id> Progreso de recompresión
GET  /api/montaje/clips?root=        Clips disponibles para montar (también los usa Recompresión)
GET  /api/montaje/thumbnail?root=&path=   Miniatura (genera si no existe)
GET  /api/montaje/fonts              Fuentes del sistema (máx. 80)
GET  /api/montaje/projects?root=     Lista de proyectos guardados
GET|POST|DELETE /api/montaje/project Cargar/guardar/borrar proyecto
GET  /api/montaje/new-project?root=  Proyecto vacío
POST /api/montaje/export             Lanzar exportación final del montaje
GET  /api/montaje/export-status/<job_id>
POST /api/montaje/analyze            Lanzar análisis+proxy para vista previa
GET  /api/montaje/analyze-status/<job_id>  Devuelve trayectoria + proxy_path al terminar
```

## Formato del proyecto de montaje (JSON)

```json
{
  "version": 1,
  "root": "/ruta/absoluta/de/origen",
  "transition_seconds": 2.0,
  "clips": [
    {
      "id": "abc123",
      "path": "/ruta/absoluta/al/mp4/convertido/o/estabilizado",
      "in": 0.0,
      "out": 12.5,
      "title": {"text": "...", "font": "/ruta/a/fuente.ttc", "image": null, "duration": 3.0},
      "stabilize": {
        "shakiness": 5, "accuracy": 15, "smoothing": 10,
        "zoom_mode": "auto_static", "zoom_percent": 0.0
      }
    }
  ]
}
```

`title` y `stabilize` son `null`/ausentes si el clip no los tiene. `stabilize` es el
único sitio donde vive esa configuración — no genera ningún fichero hasta la
exportación final.

## Cómo verificar que todo sigue funcionando en la próxima sesión

1. **Antes de reiniciar el servidor, comprobar si hay jobs reales en marcha**:
   `ps aux | grep ffmpeg`. Si hay un proceso de estabilización/exportación en curso
   (no uno tuyo de prueba), **no lo mates ni reinicies el servidor** — el hilo que lo
   lanzó vive dentro del proceso Flask, matarlo lo interrumpe. Esto ya ha pasado
   varias veces en esta sesión (análisis 4K de varias horas).
2. Arrancar: `python3 app.py` (o el `.command`), servidor en `http://localhost:5050`.
   Flask con `debug=False` **no recarga plantillas ni código solo** — hay que
   reiniciar el proceso tras **cualquier** cambio en un `.py` (las plantillas/JS/CSS
   sí se sirven frescas en cada petición, esos no necesitan reinicio).
   - En el Mac de pruebas, el `python3` del PATH por defecto (Homebrew, 3.12/3.14) no
     tenía Flask instalado, y el único con Flask (`/usr/bin/python3`, el de Apple) es
     3.9 — demasiado antiguo para la sintaxis `X | None` ya usada en el código. Se creó
     un venv del proyecto (`.venv/`, ya en `.gitignore`) con
     `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` y se lanzó
     con `.venv/bin/python app.py`. Si el arranque normal falla por `ModuleNotFoundError:
     flask` o por errores de sintaxis `|`, es este mismo problema — usar ese venv.
   - `ffmpeg-full` (necesario para `vidstabdetect`/`vidstabtransform`) tampoco estaba
     instalado en el Mac de pruebas a pesar de haber clips ya estabilizados de sesiones
     anteriores — se instaló con `brew install ffmpeg-full` (bottled, no hace falta
     compilar). Sin él, `find_ffmpeg_with_vidstab()` falla con un error claro en la UI.
2. Material de prueba real ya presente en el repo local (no en git, son personales):
   - `private/AVCHD/BDMV/STREAM/*.MTS` — clips AVCHD 1080i reales (Sony ILCE-6400).
   - `Mago de Oz/private/M4ROOT/CLIP/*.MP4` — clips 4K reales (mismo tipo de cámara).
   - `Mago de Oz/DCIM/` — vídeos/fotos de otra cámara + fotos sueltas.
   - Ya hay contenido convertido/estabilizado de sesiones anteriores en
     `private/conversion/`, `private/estabilizado/`, etc. — reutilizable para pruebas
     rápidas sin esperar a una conversión/estabilización nueva.
3. Verificar siempre **a través de la app real** (clics/fetch en el navegador o
   `curl` a los endpoints), no solo llamando a las funciones Python directamente —
   así se detectó el bug del decorador roto.

## Pendiente (explícitamente aplazado, no implementado)

- **Fase 2**: formatos `.avi`, `.mkv`, `.wmv`, `.3gp` — se listan en el escaneo bajo
  "Otros formatos" pero no se procesan. No probados, podrían tener códecs que ffmpeg
  no maneje igual de bien que H.264/MP4.
- No hay suite de tests automatizados — todo verificado manualmente/con scripts ad
  hoc contra clips reales durante el desarrollo.
- No hay purga/expiración de las carpetas de caché (`.vidstab_cache/`, `.proxies/`,
  `.miniaturas/`) — crecen sin límite.
- El zoom automático de la vista previa en canvas es una aproximación (ver
  "Hallazgos" #2) — si en algún momento se nota muy desviado del resultado real,
  revisar `autoZoomPercent()` en `static/montaje.js`.
