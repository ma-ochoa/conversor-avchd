# Estado del proyecto — documento de continuidad

> Este documento existe para que una sesión futura (humana o de Claude Code) pueda
> retomar el desarrollo leyendo **solo esto**, sin necesitar el historial de la
> conversación anterior. Complementa a `README.md` (que es de cara al usuario); este
> documento es técnico y explica el *por qué* de las decisiones, no solo el *qué*.
>
> Última actualización: sesión que añadió (1) el **historial de ajustes de
> estabilización** — borrador por clip (guardar/probar/descartar) independiente de
> renderizar, marcado de clips analizados/ajustados en el escaneo, y visibilidad
> cruzada entre Estabilización y Montaje sin recomprimir — (2) **despliegue con
> Docker** — imagen + `docker-compose.yml` + publicación automática en GHCR por GitHub
> Actions, enganchado al Watchtower ya compartido entre proyectos en este equipo — (3)
> marcar/desmarcar todo y prefijo de nombre en Conversión — (4) **carpeta de trabajo
> configurable** (`⚙️ Ajustes`, `converter/config.py`) — una única ubicación opcional,
> global a toda la app, para lo que generan Conversión/Recompresión/Montaje, en vez de
> repartido dentro de cada carpeta de origen — y (5) **rediseño del almacenamiento de
> estabilización**: cada vídeo guarda su análisis/ajustes/log junto a sí mismo
> (`stabilization_data/`, ver más abajo) en vez de en una caché centralizada, la
> salida se llama `<nombre>_stabilized.mp4` junto al original, y el panel de ajustes
> (básicos + un grupo "Avanzado" con los parámetros de vid.stab menos habituales) es
> un componente compartido con controles siempre visibles pero bloqueados en modo
> automático. Repo: https://github.com/ma-ochoa/conversor-avchd — rama `main`.
> Comprueba `git log --oneline -5` y `git status` al empezar para confirmar que sigue
> así — y ten en cuenta que puede haber cambios de otra sesión aún sin commitear
> conviviendo en el árbol de trabajo (p. ej. ficheros nuevos sin seguimiento).

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
Dockerfile                      Imagen: python:3.12-slim + ffmpeg/exiftool/fuentes vía apt
docker-compose.yml               Servicio "app" — ver sección Docker más abajo
.dockerignore                    Excluye contenido personal/generado del contexto de build
.env.example                     Plantilla de MEDIA_DIR (copiar a .env, no se sube a git)
.github/workflows/docker-publish.yml   Build + push a ghcr.io en cada push a main

app.py                          Todas las rutas Flask (una sola app, sin blueprints)

templates/_base.html            ⭐ Layout compartido: barra lateral + bloques Jinja
templates/index.html            Página de Conversión ({% extends "_base.html" %})
templates/recompresion.html     Página de Recompresión
templates/estabilizacion.html   Página de Estabilización
templates/montaje.html          Página de Montaje (editor)
templates/ajustes.html          Página de Ajustes (carpeta de trabajo global)
templates/_stab_params_panel.html  ⭐ Panel de ajustes de estabilización compartido —
                                 {% include %} parametrizado por prefix, ver detalle abajo

static/shell.js                 Recuerda la carpeta de proyecto entre módulos (localStorage)
static/conversion.js            JS de Conversión (checkboxes "marcar todo", prefijo de nombre)
static/recompresion.js          JS de Recompresión
static/ajustes.js               JS de Ajustes — usa ids "wd-*" para su selector de carpeta,
                                 NO "path-input", porque shell.js rellena cualquier
                                 #path-input con la última carpeta de PROYECTO recordada
                                 (un concepto distinto de la carpeta de trabajo global)
static/estabilizacion.js        JS de Estabilización (tabla + modal "Analizar y ajustar" +
                                 modal "Propagar a otros clips")
static/stabilize_preview.js     ⭐ Preview de estabilización en canvas — compartido entre
                                 Estabilización y Montaje (ver detalle abajo)
static/stab_params_panel.js     ⭐ Lógica del panel de ajustes compartido — ver detalle abajo
static/montaje.js               JS del editor — usa stabilize_preview.js/stab_params_panel.js
                                 para su propio modal
static/style.css                Estilos compartidos + layout de la barra lateral
static/montaje.css              Estilos del editor, reutilizados también por Estabilización
                                 (modal/canvas) — cargado desde ambas plantillas

converter/
  config.py                     ⭐ Carpeta de trabajo global — ver detalle abajo
  ffmpeg_ops.py                 Remuxeo sin pérdida (remux_clip), FFMPEG_BIN="ffmpeg"
  metadata.py                   Fecha de captura vía exiftool (DateTimeOriginal, etc.)
  naming.py                     Nombres AAAAMMDD_HHMMSS[_prefijo].ext con desambiguación
  manifest.py                   .manifest.json genérico (qué ya se procesó, por carpeta) —
                                 resuelve la carpeta de trabajo internamente (ver abajo)
  scanner.py                    Escaneo recursivo: vídeos/fotos/otros formatos, marca
                                 already_stabilized/has_analysis/stabilize_draft por clip
                                 comprobando directamente junto a cada vídeo (ya no un
                                 manifiesto centralizado)
  jobs.py                       Job de "Convertir" (remuxeo + fotos)
  fonts.py                      Fuentes del sistema (macOS y Linux/Docker) para drawtext
  thumbnails.py                 Miniaturas .jpg cacheadas (carpeta .miniaturas/)
  project.py                    Guardar/cargar proyectos de montaje (JSON)
  montaje_clips.py              Lista de clips disponibles para montar/recomprimir:
                                 convertidos (conversion/, con el borrador enlazado por
                                 origen) + estabilizados (recorre el árbol buscando
                                 *_stabilized.mp4, sin borrador adjunto)

  stabilize.py                  ⭐ Núcleo de estabilización — ver detalle abajo
  stabilize_jobs.py             Job de "Estabilizar" (independiente) — usa el borrador
                                 guardado del clip si existe, si no los parámetros
                                 globales; escribe <nombre>_stabilized.mp4 junto al original
  migrate_stabilization.py      Script de migración única del esquema antiguo (estabilizado/
                                 + .vidstab_cache/) al nuevo (co-localizado) — se ejecuta a
                                 mano, no es parte de la app en marcha
  proxy.py                      Genera/cachea proxy ligero (.proxies/) para el canvas
  analyze_jobs.py               Job de "Analizar" (solo trayectoria) — genérico, lo usan
                                 tanto Montaje como el modal de Estabilización
  timeline_export.py            ⭐ Construye el filtro ffmpeg del montaje completo
  timeline_jobs.py              Job de "Exportar montaje"

  recompress.py                 Recompresión genérica (calidad CRF + tope de resolución)
  recompress_jobs.py            Job de "Recomprimir"
```

## `converter/stabilize.py` — cómo funciona de verdad

Es el módulo más importante y el que más ha costado afinar.

**Almacenamiento: junto al vídeo, no centralizado.** Cada clip guarda su propia
carpeta `stabilization_data/` como hermana de sí mismo (o replicada con la misma ruta
relativa dentro de la carpeta de trabajo, si hay una configurada — ver
`_relocated_dir()`, que es la única función que decide esto). Dentro, con el nombre
del vídeo como prefijo:

- `<nombre>.trf` — el análisis binario de `vidstabdetect` (pase 1).
- `<nombre>_analisis.json` — metadatos del análisis: `source_size` (para invalidar la
  caché si el origen cambia), `shakiness`/`accuracy`/`stepsize`/`mincontrast` (los
  parámetros de detección con los que se generó — si alguno no coincide con lo que se
  pide, se repite el análisis), `stats` (fotogramas de bajo contraste, confianza), y
  opcionalmente `preview` (trayectoria fotograma a fotograma + fps/ancho/alto/duración,
  para la vista previa en canvas — se añade la primera vez que se pide, no hace falta
  volver a analizar para tenerla).
- `<nombre>_ajustes.json` — el borrador de ajustes guardado (ver más abajo).
- `<nombre>_log.json` — lista cronológica de acciones (`analizado`, `ajuste_guardado`,
  `ajuste_descartado`, `estabilizado`, `migrado`), cada una con marca de tiempo y los
  parámetros/resultado relevantes. Es un log de auditoría, no algo que la UI muestre
  todavía.

El vídeo ya estabilizado se guarda como `<nombre>_stabilized.mp4`, también junto al
original (o replicado en la carpeta de trabajo).

Funciones clave:

- **`ensure_analysis(root, source, shakiness, accuracy, stepsize, mincontrast)`**:
  pasada 1 de `vid.stab` (`vidstabdetect`). **Esto es lo lento** (en 4K, minutos u
  horas según duración — ver "Hallazgos" abajo). Reutiliza el `.trf` si ya existe uno
  para el `source_size` y estos 4 parámetros exactos; si no, lo regenera (sobrescribe
  — solo se guarda "el" análisis vigente de cada clip, no uno por combinación de
  parámetros como en el diseño anterior).
- **`stabilize_clip(source, dest, root, ..., shakiness, accuracy, smoothing, zoom_mode,
  zoom_percent, stepsize, mincontrast, interpol, optalgo, maxshift, maxangle)`**: pasada
  2 (`vidstabtransform`) + codificación real a `dest` (el destino lo decide quien
  llama, no esta función). Llama a `ensure_analysis` primero (con caché). Solo
  `shakiness`/`accuracy`/`stepsize`/`mincontrast` invalidan la caché de análisis; el
  resto de parámetros son solo de la pasada 2, reprocesar cambiándolos es rápido.
- **`get_preview_analysis(...)`**: para la vista previa en canvas. Llama a
  `ensure_analysis` (mismo caché) y ejecuta `vidstabtransform` con `debug=1` para
  volcar la trayectoria de cámara fotograma a fotograma **sin codificar vídeo**. El
  resultado se guarda bajo la clave `"preview"` dentro del mismo
  `<nombre>_analisis.json` (no en un fichero aparte).
- `zoom_mode`: `"auto_static"` (`optzoom=1`, el de siempre), `"auto_dynamic"`
  (`optzoom=2`), `"manual"` (`optzoom=0:zoom=X`, control tipo Pinnacle).
- El filtro siempre empieza con `yadif=mode=1:deint=interlaced` — desentrelaza
  **solo si el fotograma viene marcado como entrelazado** (AVCHD 1080i), dejando
  intacto el vídeo progresivo (4K/MP4 de cámaras modernas).
- **`has_cached_analysis(root, source, shakiness, accuracy, stepsize, mincontrast)`**:
  comprueba si el `.trf` de esos 4 parámetros ya existe y es válido, sin ejecutar
  ffmpeg. La usa `scanner.py` en cada clip del escaneo.
- **`save_stabilize_draft` / `load_stabilize_draft` / `discard_stabilize_draft`**: el
  "borrador" de ajustes por clip — ahora un fichero JSON propio
  (`<nombre>_ajustes.json`), ya no una entrada dentro de un manifiesto compartido.
- **`DEFAULT_PARAMS`** (dict) y **`is_custom_mode(params)`**: los 11 parámetros y sus
  valores de fábrica en un único sitio — los usan tanto el backend (para decidir si
  el resultado de `stabilize_clip` fue "automático" o "personalizado") como, en
  espíritu, el frontend (`STAB_DEFAULT_PARAMS`/`stabIsCustom` en
  `static/stab_params_panel.js`, duplicado ahí porque el JS no puede importar Python
  — si se cambia un valor por defecto hay que tocar los dos sitios).
- **`converter/migrate_stabilization.py`**: script de migración (no una ruta Flask;
  se ejecuta a mano, `python3 -m converter.migrate_stabilization "<carpeta>"`) del
  esquema anterior (`estabilizado/` centralizado + `.vidstab_cache/` por hash) a este.
  Mueve cada vídeo ya estabilizado a su nueva ubicación, migra el borrador si existía,
  y copia el `.trf` antiguo *solo* si hay uno que corresponda exactamente al
  shakiness/accuracy del borrador (o 5/15 por defecto) — si no, no se arrastra (se
  puede volver a analizar). Seguro de ejecutar más de una vez. Ejecutado de verdad en
  esta sesión contra los datos reales del proyecto: 8 clips migrados, 1 con caché de
  análisis migrada (los otros 7 no tenían ya un `.trf` que coincidiera, así que
  tocará re-analizarlos si se quieren volver a ajustar).

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

## Panel de ajustes compartido (`templates/_stab_params_panel.html` + `static/stab_params_panel.js`)

Petición del usuario: explicar en la propia UI qué hace cada ajuste, que los
controles estén **siempre visibles** (bloqueados en gris en modo automático, en vez de
ocultos) y se desbloqueen al pasar a "Personalizado", y exponer un grupo "Avanzado"
con los parámetros de vid.stab que hasta ahora estaban ocultos por completo
(`accuracy`, `stepsize`, `mincontrast`, `interpol`, `optalgo`, `maxshift`, `maxangle`)
— cada uno con su explicación.

Se usa en tres sitios (panel masivo de Estabilización, modal por clip de
Estabilización, modal de Montaje), así que en vez de triplicar el HTML/JS a mano:

- **`templates/_stab_params_panel.html`**: un `{% include %}` de Jinja parametrizado
  por `{% set prefix = "..." %}` antes de incluirlo — cada sitio usa un prefijo
  distinto (`bulk-stab`, `clip-stab`, `montaje-stab`) para que los ids no choquen al
  convivir varios en la misma página (el modal de Montaje y el panel masivo de
  Estabilización, aunque en páginas distintas, comparten el mismo patrón).
- **`static/stab_params_panel.js::createStabParamsPanel(prefix, {onChange})`**: dado
  el mismo prefijo, engancha todos los controles (bloqueo/desbloqueo con el radio
  automático/personalizado, actualización de las etiquetas de valor, mostrar/ocultar
  la fila de zoom manual) y devuelve `{getParams(), setParams(draft), element}`.
  `setParams(null)` deja el panel en modo automático con los valores de fábrica.
  `STAB_DEFAULT_PARAMS`/`stabIsCustom()` en este fichero duplican
  `DEFAULT_PARAMS`/`is_custom_mode()` de `converter/stabilize.py` — el JS no puede
  importar Python, así que si se cambia un valor por defecto hay que tocar los dos
  sitios.
- Los tres sitios que lo usan (`static/estabilizacion.js` para el panel masivo y el
  modal por clip, `static/montaje.js` para su modal) ya no tienen su propia lógica de
  mostrar/ocultar ni de leer cada `<input>` a mano — solo llaman a
  `createStabParamsPanel(...)`, y donde antes había un `montajeStabParams()`/
  `clipStabParams()` a medida ahora se llama a `panel.getParams()`.

## Historial de ajustes de estabilización (borrador por clip, entre módulos)

Petición del usuario: poder analizar/ajustar un clip en Estabilización, guardar o
descartar esos ajustes, y que el resto de la app (el escaneo, Montaje) los vea sin
tener que rebuscar en carpetas ni recomprimir nada. Piezas:

- **Almacén**: un fichero JSON propio por clip
  (`stabilization_data/<nombre>_ajustes.json`, junto al vídeo — ver la sección de
  `stabilize.py` más arriba), no una entrada dentro de un manifiesto compartido como
  en el diseño original de esta función. Independiente de si el clip se ha llegado a
  analizar o renderizar: solo guarda qué parámetros eligió el usuario la última vez.
- **Rutas**: `POST /api/stabilize-draft` (guarda) y `DELETE /api/stabilize-draft`
  (descarta), body `{root, path, shakiness?, accuracy?, smoothing?, zoom_mode?,
  zoom_percent?, stepsize?, mincontrast?, interpol?, optalgo?, maxshift?, maxangle?}`.
- **Escaneo** (`scanner.py`): cada clip de vídeo lleva `has_analysis` (¿existe un
  `.trf` válido para los parámetros de detección del borrador, o los de por defecto si
  no hay borrador?) y `stabilize_draft` (el borrador tal cual, o `null`). La tabla de
  Estabilización pinta con esto el estado: `—` / `🔍 analizado` / `🩹 ajustado`.
- **Página de Estabilización** (`estabilizacion.js`): botón "🔍 Analizar y ajustar"
  por fila abre el modal compartido, precargado con el borrador si existe — y si
  `has_analysis` ya es cierto, dispara el análisis (que será casi instantáneo, cache
  hit) automáticamente, sin esperar a que el usuario pulse "Analizar clip" (petición
  explícita del usuario: "si un vídeo se ha analizado previamente, al pinchar en
  analizar y ajustar mostrará la ventana de edición de ajustes"). "Guardar ajuste"/
  "Descartar ajuste guardado" llaman a las rutas de arriba y actualizan la fila sin
  recargar toda la tabla. El botón masivo "Estabilizar marcados" sigue mandando unos
  parámetros globales al job, pero **`stabilize_jobs.py` comprueba el borrador de cada
  clip y lo usa en vez de esos parámetros globales si existe** — sin ningún cambio en
  el frontend, es puramente un `load_stabilize_draft` antes de llamar a
  `stabilize_clip` en `_run_job`.
- **Propagar a otros clips**: botón "Propagar a otros clips…" en el modal por clip —
  abre un segundo modal listando los demás clips de la **misma carpeta** (mismo
  directorio padre en la ruta relativa del escaneo), y copia el ajuste actual del
  panel a cada uno marcado, llamando a `POST /api/stabilize-draft` una vez por clip
  destino desde el frontend (`static/estabilizacion.js` — sin ninguna ruta nueva en
  el backend).
- **Montaje** (`montaje_clips.py` + `montaje.js`): `montaje_clips.py` invierte el
  manifiesto de `conversion/` (origen → nombre de salida) para, dado un fichero ya
  convertido, encontrar su clip original y adjuntarle `stabilize_draft` si lo tiene
  (los clips ya estabilizados se descubren aparte, recorriendo el árbol en busca de
  `*_stabilized.mp4` — ver la sección de `stabilize.py` — y nunca llevan borrador
  adjunto). La cuadrícula de clips pinta una insignia "🩹 ajuste de estabilización
  guardado" y, al arrastrar el clip a la línea de tiempo, `addClipToTimeline` copia
  ese borrador a `item.stabilize` automáticamente.
  **Importante — guarda de doble estabilización**: esto solo pasa si
  `clip.source === "convertido"` (el clip viene de `conversion/`, aún sin
  estabilizar). Un clip que ya viene de "estabilizado" es un vídeo YA procesado con
  `vid.stab`; si se le aplicase además el borrador como `item.stabilize`, la
  exportación final le metería `vidstabtransform` una segunda vez encima de un vídeo
  que ya no tiembla — con resultados impredecibles. La insignia y la herencia se
  omiten a propósito para esos clips (el borrador puede seguir viéndose en la propia
  página de Estabilización, solo no se hereda en Montaje).

## Carpeta de trabajo configurable (`converter/config.py`)

Petición del usuario: poder elegir dónde se guarda todo lo que la app genera —
`conversion/`, `recompresion/`, `montaje/` (proyectos y exportaciones), `.proxies/`,
`.miniaturas/`, y (desde esta sesión) también `stabilization_data/`/
`<nombre>_stabilized.mp4` — en vez de que quede siempre repartido dentro de cada
carpeta de origen que se escanea.

- **Config global, no por proyecto**: `converter/config.py` guarda un único
  `working_dir` opcional en `~/.conversor-avchd/config.json` (fuera de cualquier
  carpeta de proyecto, a propósito — tiene que poder configurarse independientemente
  de qué carpeta de origen se esté usando en cada momento). `Path.home()` funciona
  igual en macOS nativo (`/Users/usuario`) que en Docker (`HOME=/data`, ver sección
  Docker) — en el contenedor el fichero queda dentro del volumen montado, así que
  también persiste.
- **`resolve_output_base(root) -> Path`**: la única función que importa. Devuelve
  `working_dir` si hay uno configurado, si no devuelve `root` tal cual (comportamiento
  de siempre). **Es idempotente** — `resolve_output_base(resolve_output_base(root))`
  da el mismo resultado que llamarla una vez — porque cuando hay `working_dir`
  configurado ignora su argumento por completo. Esta propiedad fue clave para poder
  aplicar el cambio con seguridad: se pudo llamar `resolve_output_base()` en **cada**
  sitio que construye una ruta de salida (más de 15, repartidos por medio proyecto),
  sin tener que rastrear con precisión quirúrgica cuál de esos sitios es "el primero"
  en tocar cada `root` — llamarla de más nunca rompe nada.
- **Dónde se aplicó** (todo lo que antes hacía `root / NOMBRE_SUBCARPETA` para
  *generar/cachear* algo, no para *leer el origen*): `manifest.py::_manifest_path`
  (cubre `load_manifest`/`record_entry`/`remove_entry` en todos sus llamantes:
  scanner, jobs, recompress_jobs, montaje_clips), `thumbnails.py::_thumb_cache_path`,
  `proxy.py::_proxy_path`, `project.py::_projects_dir` + `exports_dir` (nueva
  función, la usa `timeline_jobs.py` en vez de construir la ruta a mano), y los
  `output_dir` calculados directamente en `scanner.py`, `jobs.py`,
  `recompress_jobs.py`. **Estabilización es distinta**: no llama a
  `resolve_output_base()` en cada sitio, sino que `stabilize.py::_relocated_dir(root,
  source_dir)` la llama una vez y decide entre "junto al vídeo" (si no hay carpeta de
  trabajo) o "misma ruta relativa dentro de la carpeta de trabajo" (si la hay) — ver
  la sección de `stabilize.py` más arriba.
- **Qué NO cambia**: el `root`/carpeta de origen que se escanea sigue siendo
  exactamente el mismo concepto de siempre (dónde están los `.MTS`/`.mp4` originales) —
  eso nunca se resuelve contra la carpeta de trabajo, solo lo que se *genera* a partir
  de ahí. Por eso `file_path.relative_to(root_path)` en `scanner.py`, o el campo
  `"root"` que se guarda dentro de un proyecto de montaje (metadato sin uso real hoy en
  el frontend), siguen usando el `root` sin resolver.
- **Migración de datos ya generados con el esquema anterior**: a diferencia de
  conversión/recompresión/montaje (donde cambiar la carpeta de trabajo simplemente no
  toca lo ya generado en la ubicación anterior), para estabilización el usuario pidió
  migrar automáticamente lo que ya hubiera — ver `converter/migrate_stabilization.py`
  en la sección de `stabilize.py` más arriba.
- **UI**: página nueva `⚙️ Ajustes` (`templates/ajustes.html` + `static/ajustes.js`),
  con su propio selector de carpeta usando ids `wd-path-input`/`wd-go-btn`/etc en vez
  de `path-input` — `shell.js` rellena *cualquier* `#path-input` que encuentre en el
  DOM con la última carpeta de *proyecto* recordada (un concepto distinto, ver
  `static/shell.js`), así que reutilizar ese id habría hecho que el campo se
  sobrescribiera solo nada más cargar la página.
- Rutas: `GET/POST /api/config`, body `{"working_dir": "ruta" | null}`. Verificado de
  verdad en esta sesión: convertido un clip real con una carpeta de trabajo distinta a
  la de origen, confirmado que el fichero aparece en la carpeta de trabajo (no en la de
  origen), confirmado que Montaje lista ese clip aunque el campo "carpeta del proyecto"
  de esa página apunte a otra carpeta distinta, y confirmado que quitar la carpeta de
  trabajo revierte el comportamiento al de siempre.

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

Relativas a la carpeta que el usuario escanea (el "root" de cada operación) — o a la
**carpeta de trabajo** configurada en Ajustes, si hay una (ver
`resolve_output_base()` más arriba); por defecto son la misma carpeta. Todas están en
`.gitignore` — nunca deben subirse al repo, contienen datos/vídeo del usuario o caché
regenerable:

| Carpeta | Contenido | Módulo |
|---|---|---|
| `conversion/` | Vídeos/fotos remuxeados | `jobs.py` |
| `recompresion/` | Vídeos recomprimidos (formato no soportado o reducción de tamaño) | `recompress_jobs.py` |
| `montaje/proyectos/*.json` | Proyectos de montaje guardados | `project.py` |
| `montaje/*_final.mp4` | Exportaciones finales del montaje | `timeline_jobs.py` |
| `.miniaturas/` | Miniaturas .jpg cacheadas | `thumbnails.py` |
| `.proxies/` | Proxies ligeros (640px) para el canvas | `proxy.py` |

Estas, en cambio, viven **junto a cada vídeo** (o replicadas con la misma ruta
relativa dentro de la carpeta de trabajo — ver `stabilize.py::_relocated_dir`), no
centralizadas bajo el root/carpeta de trabajo como las de arriba:

| Ubicación | Contenido | Módulo |
|---|---|---|
| `<carpeta del vídeo>/stabilization_data/` | `<nombre>.trf` (análisis), `<nombre>_analisis.json` (stats + trayectoria de preview), `<nombre>_ajustes.json` (borrador), `<nombre>_log.json` (histórico de acciones) — por vídeo | `stabilize.py` |
| `<carpeta del vídeo>/<nombre>_stabilized.mp4` | El vídeo ya estabilizado | `stabilize_jobs.py` |

Ninguna de estas carpetas tiene límite de tamaño ni expiración — si en el futuro se
usa la app con muchos clips durante mucho tiempo, podría valer la pena añadir una
forma de purgar cachés antiguas. No implementado, no pedido todavía.

## Rutas Flask (API completa)

```
GET  /                              Página de Conversión
GET  /recompresion                  Página de Recompresión
GET  /estabilizacion                Página de Estabilización
GET  /montaje                       Página de Montaje (editor)
GET  /ajustes                       Página de Ajustes (carpeta de trabajo global)
GET|POST /api/config                Leer/fijar la carpeta de trabajo global
                                     ({"working_dir": "ruta" | null})
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

## Despliegue con Docker

Petición del usuario: contenerizar la app, publicarla en GitHub, y que se
auto-actualice con Watchtower en cada cambio. Decisiones y puntos a tener en cuenta:

- **`ffmpeg` de Debian YA trae `libvidstab`/`libfreetype`/`libx264`/etc. de serie**
  (comprobado con `docker run python:3.12-slim` + `apt-get install ffmpeg` +
  `ffmpeg -filters | grep vidstab`) — a diferencia de macOS, donde hace falta el
  paquete aparte `ffmpeg-full`. Por eso el `Dockerfile` instala un único `ffmpeg` vía
  `apt`, no dos binarios distintos. `find_ffmpeg_with_vidstab()` (en `stabilize.py`)
  no necesitó ningún cambio: sus rutas candidatas de Homebrew simplemente no existen
  en Linux y cae al *fallback* genérico (`shutil.which("ffmpeg")` + comprobar que
  tiene `vidstabdetect` en `-filters`), que sí encuentra el `ffmpeg` de `apt`.
- **Bug real que habría hecho el contenedor inalcanzable**: `app.py` tenía
  `app.run(host="127.0.0.1", ...)` fijo. Dentro de un contenedor, escuchar solo en
  `127.0.0.1` significa que ni siquiera el *port mapping* de Docker (`-p 5050:5050`)
  llega a la app — hace falta `0.0.0.0`. Se arregló leyendo el host de una variable de
  entorno (`HOST`, por defecto `"127.0.0.1"` para no cambiar el comportamiento nativo
  en macOS) que el `docker-compose.yml` fija a `0.0.0.0`. Se detectó probando de
  verdad con `curl`/navegador contra el contenedor, no dando el despliegue por bueno
  solo porque `docker build`/`docker compose up` no dieran error.
- **Selectores nativos de macOS** (`pick_folder`/`pick_file`, AppleScript vía
  `osascript`) ya comprobaban `platform.system() != "Darwin"` de antes — dentro de
  Docker devuelven un error legible en vez de romperse, sin necesitar ningún cambio.
- **Fuentes** (`converter/fonts.py`): añadidas rutas típicas de Linux
  (`/usr/share/fonts`, `/usr/local/share/fonts`, `~/.fonts`) a las de macOS, y
  cambiado `iterdir()` por `rglob("*")` porque en Linux las fuentes van en
  subcarpetas por familia (`/usr/share/fonts/truetype/dejavu/...`), no sueltas en la
  carpeta como en macOS. El `Dockerfile` instala `fonts-dejavu-core` y
  `fonts-liberation` para que el título del montaje tenga con qué trabajar.
- **Carpeta de medios**: se monta la carpeta indicada en `MEDIA_DIR` (fichero `.env`,
  no versionado — ver `.env.example`) en `/data` dentro del contenedor, y se fija
  `HOME=/data` para que `Path.home()` (usado como valor por defecto del campo de
  carpeta de cada página) apunte ahí. Todo lo que la app genera se escribe dentro de
  esa misma carpeta montada — persiste en el Mac igual que en la instalación nativa.
- **Watchtower — NO se levanta uno propio**: este equipo ya tiene un Watchtower
  compartido corriendo para ~15 proyectos distintos
  (`~/Desarrollo/watchtower/docker-compose.yml`, `--label-enable`, vigilando
  contenedores de `ghcr.io/ma-ochoa/*` entre otros). `docker-compose.yml` de este
  proyecto solo añade la etiqueta `com.centurylinklabs.watchtower.enable=true` al
  servicio `app` — ese Watchtower ya existente lo recoge automáticamente. **Si en el
  futuro ese Watchtower compartido deja de existir, habría que añadir aquí un
  servicio `watchtower` propio** (`containrrr/watchtower`, montando
  `/var/run/docker.sock`, con `--label-enable`) — no se hizo por defecto para no
  duplicar infraestructura ni arriesgar un conflicto de nombre de contenedor (pasó
  exactamente eso al probar: `docker compose up` falló con "container name /watchtower
  already in use" hasta quitar el servicio propio).
- **Imagen**: `ghcr.io/ma-ochoa/conversor-avchd`, mismo patrón de nombre que el resto
  de proyectos de este usuario en GHCR. `docker-compose.yml` declara `image:` (lo que
  vigila Watchtower) **y** `build: .` a la vez — así `docker compose build` en local
  genera una imagen con el mismo nombre que la de producción (útil para probar antes
  de hacer push), y en el servidor real basta con `docker compose pull && docker
  compose up -d` sin necesitar el código fuente ni compilar nada.
- **CI**: `.github/workflows/docker-publish.yml` construye y publica en cada push a
  `main` usando el `GITHUB_TOKEN` automático de Actions (con
  `permissions: packages: write`) — no hace falta ningún secreto configurado a mano.
  Etiqueta la imagen como `latest` y también con el hash corto del commit.
- **Visibilidad del paquete en GHCR**: por defecto, un paquete publicado así queda
  **privado** aunque el repo sea público — Watchtower necesitaría credenciales
  (`docker login ghcr.io`) para poder descargarlo si sigue así. Revisar en
  https://github.com/users/ma-ochoa/packages/container/conversor-avchd/settings si
  hace falta cambiar la visibilidad a pública (o configurar login en la máquina que
  corre Watchtower) tras el primer push.

Probado de verdad en esta sesión (no solo `docker build` sin errores): contenedor
arrancado con `docker compose up -d`, healthcheck en verde, `ffmpeg -filters` con
`vidstabdetect`/`vidstabtransform` dentro del contenedor, `exiftool -ver` funcionando,
escaneo real de una carpeta montada vía `/api/scan`, conversión real de un clip que
apareció correctamente en el Mac anfitrión fuera del contenedor, y fuentes Linux
detectadas vía `/api/montaje/fonts`.

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
   - Ya hay clips estabilizados de sesiones anteriores junto a sus originales en
     `private/AVCHD/BDMV/STREAM/*_stabilized.mp4` (migrados en esta sesión al esquema
     nuevo) — reutilizable para pruebas rápidas sin esperar a una estabilización nueva.
3. Verificar siempre **a través de la app real** (clics/fetch en el navegador o
   `curl` a los endpoints), no solo llamando a las funciones Python directamente —
   así se detectó el bug del decorador roto.

## Pendiente (explícitamente aplazado, no implementado)

- **Fase 2**: formatos `.avi`, `.mkv`, `.wmv`, `.3gp` — se listan en el escaneo bajo
  "Otros formatos" pero no se procesan. No probados, podrían tener códecs que ffmpeg
  no maneje igual de bien que H.264/MP4.
- No hay suite de tests automatizados — todo verificado manualmente/con scripts ad
  hoc contra clips reales durante el desarrollo.
- No hay purga/expiración de las carpetas de caché (`stabilization_data/`,
  `.proxies/`, `.miniaturas/`) — crecen sin límite.
- El zoom automático de la vista previa en canvas es una aproximación (ver
  "Hallazgos" #2) — si en algún momento se nota muy desviado del resultado real,
  revisar `autoZoomPercent()` en `static/stabilize_preview.js`.
