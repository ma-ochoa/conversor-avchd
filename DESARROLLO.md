# Estado del proyecto — documento de continuidad

> Este documento existe para que una sesión futura (humana o de Claude Code) pueda
> retomar el desarrollo leyendo **solo esto**, sin necesitar el historial de la
> conversación anterior. Complementa a `README.md` (que es de cara al usuario); este
> documento es técnico y explica el *por qué* de las decisiones, no solo el *qué*.
>
> Última actualización: **dos líneas de trabajo en paralelo que se unieron aquí**.
>
> Por un lado: historial de ajustes de estabilización (borrador por clip
> guardar/probar/descartar, visible entre Estabilización y Montaje), **despliegue con
> Docker** (imagen + `docker-compose.yml` + publicación en GHCR por GitHub Actions,
> enganchado al Watchtower compartido), marcar/desmarcar todo y prefijo de nombre en
> Conversión, **carpeta de trabajo configurable** (`⚙️ Ajustes`, `converter/config.py`)
> global a toda la app, y **rediseño del almacenamiento de estabilización**: cada vídeo
> guarda su análisis/ajustes/log junto a sí mismo (`stabilization_data/`) y la salida se
> llama `<nombre>_stabilized.mp4` junto al original.
>
> Por otro: los módulos de **Importación** (quinto) y **Ubicación** (sexto), sobre el
> paquete `importer/`, independiente de Flask y de `converter/`.
>
> Repo: https://github.com/ma-ochoa/conversor-avchd — rama `main`. Comprueba
> `git log --oneline -5` y `git status` al empezar para confirmar que sigue así — y ten
> en cuenta que puede haber cambios de otra sesión aún sin commitear conviviendo en el
> árbol de trabajo.

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
  (hardcoded en `app.py` y en `Iniciar Conversor de vídeo.command`).
- **Frontend**: HTML/CSS/JS servidos por Flask (`templates/`, `static/`), sin build,
  sin framework, sin dependencias npm. **6 páginas** compartiendo un layout base con
  barra lateral (`templates/_base.html`, `{% extends %}`): `/importacion`, `/ubicacion`,
  `/` (Conversión), `/recompresion`, `/estabilizacion`, `/montaje`. Cada página tiene su
  propio JS independiente (nada de SPA/router — son recargas de página normales; la barra
  lateral es visualmente persistente porque el layout es idéntico en las 6, no porque
  no haya recarga). `static/shell.js` (cargado en todas) recuerda en `localStorage` la
  última carpeta de proyecto usada y precarga el campo `#path-input` de la página que
  sea — ver "Hallazgos" sobre el orden de ejecución de scripts que esto exige.
  Importación no tiene `#path-input` (su origen no es una carpeta de proyecto), así que
  `shell.js` simplemente no hace nada ahí.
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
  dentro de la propia carpeta que el usuario está procesando (ver más abajo). La única
  excepción es el importador, cuyo estado es global y vive en `~/.conversor-importador/`.

## Mapa de archivos

```
Dockerfile                      Imagen: python:3.12-slim + ffmpeg/exiftool/fuentes vía apt
docker-compose.yml               Servicio "app" — ver sección Docker más abajo
.dockerignore                    Excluye contenido personal/generado del contexto de build
.env.example                     Plantilla de MEDIA_DIR (copiar a .env, no se sube a git)
.github/workflows/docker-publish.yml   Build + push a ghcr.io en cada push a main

app.py                          Todas las rutas Flask (una sola app, sin blueprints)

templates/_base.html            ⭐ Layout compartido: barra lateral + bloques Jinja
templates/importacion.html      Página de Importación
templates/index.html            Página de Conversión ({% extends "_base.html" %})
templates/recompresion.html     Página de Recompresión
templates/estabilizacion.html   Página de Estabilización
templates/montaje.html          Página de Montaje (editor)
templates/ajustes.html          Página de Ajustes (carpeta de trabajo global)
templates/_stab_params_panel.html  ⭐ Panel de ajustes de estabilización compartido —
                                 {% include %} parametrizado por prefix, ver detalle abajo

static/shell.js                 Recuerda la carpeta de proyecto entre módulos (localStorage)
static/importacion.js           JS de Importación
static/importacion.css          Estilos propios de Importación
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

importer/                       ⭐ Paquete del importador — ver sección propia abajo
  config.py                     Configuración global (~/.conversor-importador/config.json)
  exif.py                       Lectura de metadatos EN LOTE con exiftool (-@ -)
  cameras.py                    Modelo EXIF -> nombre de carpeta + saneado de nombres
  sources.py                    Detección de tarjetas montadas y carpetas volcadas
  media.py                      Clasificación (JPG/RAW/vídeo), agrupación por cámara y día
  plan.py                       Plan de destino (función pura, sin tocar disco)
  copier.py                     Copia con checksum SHA-256 y escritura a .parcial
  history.py                    Historial global (duplicados + pendientes de subir al NAS)
  jobs.py                       Job de "Importar" (copiar → verificar → borrar → subir)
  thumbs.py                     Miniaturas del origen (RAW vía preview embebido, HEIC vía sips)
  nas.py                        Envío al NAS: Synology File Station / SFTP / FTP(S)
  nas_jobs.py                   Job de subida independiente (reintentar pendientes)
  phones.py                     Detecta móviles USB por ioreg (rápido, sin dependencias)
  mtp.py                        Lee carpetas y descarga del móvil por MTP (bindings gphoto2)
  mtp_scan.py                   ⭐ Convierte el móvil en un «escaneo» igual que una tarjeta
  mtp_jobs.py                   Solo restos del flujo antiguo (descargas sin importar)

  ── módulo Ubicación (mismo paquete, ver sección propia abajo) ──
  geoindex.py                   .ubicaciones.json: qué archivo tiene GPS y cuál no
  groups.py                     Agrupación en sesiones por cercanía en el tiempo
  gpx.py                        Lectura de tracks GPX (y conversión UTC → hora local)
  geomatch.py                   Cruce por hora con referencias + haversine
  geowrite.py                   Escritura de GPS en EXIF, con copia de seguridad
  location_jobs.py              Jobs de asignar ubicación y de reindexar
  places.py                     Buscador Nominatim (OpenStreetMap) con límite de 1 req/s

static/vendor/leaflet.js|.css   Leaflet 1.9.4 vendorizado (el mapa, sin CDN)
templates/ubicacion.html        Página de Ubicación
static/ubicacion.js|.css        JS y estilos de Ubicación
```

## `importer/` — el módulo de Importación

**Está deliberadamente aislado del resto.** No importa nada de `converter/` ni de Flask:
`app.py` solo llama a sus funciones. Esto es un requisito explícito del usuario — la idea
es poder sacarlo tal cual a una aplicación independiente en el futuro, porque el flujo
"tarjeta → disco → NAS" tiene sentido por sí solo, sin el conversor de vídeo.

Flujo completo, todo dentro de una sola página (`/importacion`):

1. **Detectar** (`sources.py`) — tarjetas montadas (`/Volumes` en macOS vía `diskutil
   info -plist`, `GetLogicalDrives`+`GetDriveTypeW` en Windows, `/media`|`/run/media` en
   Linux) **y** carpetas del Escritorio/Descargas que parezcan un volcado manual. Ambas
   cosas son "orígenes" idénticos a partir de ahí.
2. **Escanear** (`media.py` + `exif.py`) — clasifica en JPG / RAW / vídeo / sidecar,
   agrupa por cámara (modelo EXIF) y por día. El escaneo se guarda en memoria en `app.py`
   (`_scans`, últimos 5) y el navegador solo maneja un `scan_id`: una tarjeta puede tener
   miles de ficheros y no tiene sentido reenviarlos en cada paso.
3. **Planificar** (`plan.py`) — función pura que devuelve la ruta destino exacta de cada
   fichero, más el árbol de carpetas resultante. Se muestra antes de copiar nada.
4. **Importar** (`jobs.py`) — un solo job encadena cuatro fases: copiar+verificar →
   borrar del origen → subir al NAS → resumen. Mismo patrón de hilo + polling que el
   resto de módulos.

Detalles que no son evidentes leyendo el código:

- **El nombre se decide por grupo, no por fichero.** Un grupo es "mismo directorio +
  mismo stem", o sea un RAW y su JPG. Se calcula un único nombre base para todo el grupo
  y se comprueba la colisión en *todas* sus carpetas destino a la vez. Sin esto, dos
  disparos en el mismo segundo desambiguarían de forma distinta en `JPG/` y en `RAW/` y
  el par quedaría desemparejado.
- **`copier.py` escribe a `<destino>.parcial` y renombra al final.** Una interrupción
  (cierre de la app, tarjeta desconectada) nunca deja en el destino un fichero truncado
  con aspecto de completo.
- **El borrado del origen exige verificación.** Si `verify_checksum` está desactivado no
  se borra nada, y si falla *un solo* fichero de la importación tampoco se borra nada
  (no solo el que falló). Es la única salvaguarda contra perder el único ejemplar.
- **La detección de duplicados NO hashea la tarjeta.** La clave es
  `nombre|tamaño|fecha_captura` (`media.import_key`). Hashear 64 GB solo para saber si ya
  se importó costaría más que la propia copia; el SHA-256 real se calcula al copiar, que
  es cuando hay que leer el fichero de todos modos.
- **`exif.py` lanza UN exiftool por lote de 400 ficheros** (`-@ -` con la lista por
  stdin), no uno por fichero como `converter/metadata.py`. Medido sobre material real:
  599 ficheros / 16 GB escaneados en **2,7 s**. Con un exiftool por fichero serían
  minutos.

## El módulo de Ubicación (`/ubicacion`)

Vive en el mismo paquete `importer/` y con la misma regla: **nada de Flask ni de
`converter/` dentro**. Es la continuación natural del importador (tarjeta → disco → NAS →
*y que además salgan en el mapa*), y debe poder salir con él a una app independiente.

**El problema que resuelve**: las cámaras sin GPS no guardan dónde se tomó la foto, así
que Synology Photos no las sitúa en el mapa. El móvil sí lo guarda. Si el móvil estaba en
el mismo sitio a la misma hora, su posición sirve para la foto de la cámara.

Flujo: cargar índice → agrupar en sesiones → deducir desde referencias → asignar (mapa) →
escribir en el archivo.

Decisiones de diseño que no se ven en el código:

- **El índice (`geoindex.py`) vive en la carpeta de fotos, no en la configuración
  global.** Es `.ubicaciones.json` en la raíz del destino, con rutas **relativas**. Así
  viaja con las fotos, sobrevive a mover la carpeta de disco, y evita releer el EXIF de
  miles de ficheros en cada carga. Lo alimenta la importación (`jobs.py`), y
  `geoindex.rebuild()` lo reconstruye para carpetas anteriores a este módulo.
- **Las sesiones NO se separan por cámara** (`groups.py`). Es contraintuitivo pero es el
  punto clave: si la cámara y el móvil disparan a la vez en el mismo sitio tienen que caer
  en la misma sesión, porque es justo lo que permite usar la posición del móvil para la
  cámara. Solo se corta por hueco temporal (1 h por defecto, ajustable).
- **La propuesta se hace por sesión, no por fichero** (`geomatch.py`). Los ficheros de una
  sesión están por definición juntos en tiempo y lugar; darles posiciones distintas sería
  fingir una precisión que no existe. Se compara contra el **centro temporal** de la
  sesión, que es lo que menos se desvía cuando dura un rato.
- **Siempre se muestra el desfase con el que se dedujo.** Es una aproximación declarada,
  no una medición. Si la sesión ya tenía alguna foto con GPS, se contrasta la propuesta
  con ella (haversine) y se avisa en rojo si cae a más de 500 m.
- **Escribir el GPS modifica el archivo original.** Es la única parte de toda la app que
  lo hace, y es inevitable: Synology Photos lee la posición de dentro del fichero, no de
  un sidecar. Por eso `geowrite.py` guarda una copia intacta en `_originales_sin_gps/`
  antes de tocar nada, nunca la pisa si ya existe (la buena es la primera), y hay un
  "Deshacer" que restaura. **Tras escribir se relee el archivo para confirmar que la
  posición quedó dentro**: si exiftool devuelve 0 pero el formato no admitía el campo, el
  índice mentiría.
- **Fotos y vídeos usan tags distintos.** Las fotos, `GPSLatitude`/`GPSLongitude` +
  sus `Ref` (N/S/E/W, porque el EXIF guarda el valor absoluto y el signo aparte). Los
  MP4/MOV no usan EXIF: la posición va en `QuickTime:GPSCoordinates` como un único texto
  `"lat lon"`, más XMP para quien lea eso.

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

11. **En macOS, listar `~/Desktop` sin permiso TCC NO da error: se queda bloqueado
    durante muchísimo tiempo.** Comprobado empíricamente: `Path.home()/"Desktop"`
    responde a `.is_dir()` al instante, pero `.iterdir()` no vuelve (el sistema espera a
    un diálogo de autorización que en un proceso lanzado sin interfaz puede no llegar a
    aparecer). Una medición que quedó corriendo en segundo plano acabó devolviendo
    resultados **a los 5667 s (94 minutos)** — o sea que no es un bloqueo eterno, pero a
    efectos prácticos lo es: colgaba la petición HTTP entera y con ella la interfaz.
    `~/Downloads` funcionaba desde una terminal ya autorizada y se bloqueaba igual desde
    el proceso Flask, así que depende de qué app lanzó el proceso, no de la carpeta.
    Solución en `importer/sources.py::_listdir()`: el listado se hace en un hilo daemon
    del que se desiste a los 3 s, y la carpeta se apunta en `_blocked_folders` para no
    reintentarla en cada carga de página (la primera llamada tarda ~6 s, las siguientes
    13 ms). La UI avisa de que hay que dar el permiso. **No basta con un `try/except
    PermissionError` ni con un deadline comprobado en el bucle: la llamada no vuelve.**
12. **En macOS, muchas cosas que parecen un fichero son carpetas llenas de imágenes.**
    Al desbloquear la detección salió que el Escritorio/Descargas del usuario contenía
    `iPhoto.app`, `Cyberduck.app` y similares, y todas se ofrecían como "orígenes"
    porque un bundle `.app` lleva iconos PNG dentro y `_has_media()` los daba por buenos.
    Peor sería una `.photoslibrary` (la fototeca de Fotos): miles de JPG que además
    tardarían una eternidad en recorrerse. Filtrado por extensión de bundle en
    `importer/sources.py::is_bundle()`, aplicado en tres sitios: la lista de orígenes, el
    descenso de `_has_media()`, y el `os.walk` de `importer/media.py::_iter_files()`
    (si no, elegir a mano una carpeta que contenga una `.app` importaría sus iconos como
    fotos).
13. **Los MP4 XAVC de Sony (carpeta `M4ROOT`) no traen `Make`/`Model` en EXIF.** El
    modelo va en `XML:DeviceModelName` y el fabricante en `XML:DeviceManufacturer`. Sin
    leer esos dos tags, los vídeos 4K quedaban en un grupo "sin identificar" separado de
    las fotos de la misma cámara. Ya está contemplado en `importer/exif.py`.
14. **Las tarjetas traen carpetas de servicio con material que parece real.**
    `M4ROOT/THMBNL/` guarda un `.JPG` por clip XAVC (se importaban como fotos de verdad)
    y `M4ROOT/SUB/` una copia en baja resolución de cada vídeo. Están en
    `importer/media.py::_IGNORED_DIRS` junto con `CANONMSC`, `MISC`, `AVF_INFO`,
    `CLIPINF` y `PLAYLIST`. Ojo: **`STREAM` NO debe excluirse** — ahí viven los `.MTS`.
15. **`subprocess.run(capture_output=True)` es incompatible con pasar `stdout`/`stderr`
    explícitos** — lanza `ValueError`, no un fallo silencioso. Pasó al escribir
    `importer/thumbs.py`, donde algunas ramas redirigen stdout a un fichero (el
    `exiftool -b -PreviewImage` de los RAW) y otras no. La solución es no usar
    `capture_output` y pasar siempre `stdout=`/`stderr=` a mano.
16. **Los errores de red de `requests` incluyen la URL completa de la petición.** Como el
    login de Synology se hacía por GET con `passwd=` en la query, un fallo de conexión
    mostraba **la contraseña en claro** en la interfaz. Corregido en dos frentes en
    `importer/nas.py`: todas las llamadas a `entry.cgi` van por POST con los parámetros
    en el cuerpo (que además evita que las credenciales acaben en el log de accesos del
    NAS), y `_redact()` limpia cualquier resto del texto de error antes de mostrarlo.
17. **El Python de Homebrew en macOS no lee el almacén de certificados del sistema.**
    Cualquier HTTPS con `urllib` falla con `CERTIFICATE_VERIFY_FAILED: unable to get local
    issuer certificate`, que además parece un problema de red y no lo es — el buscador de
    lugares daba "necesita conexión a internet" estando conectado. Se arregla pasando un
    contexto SSL construido con `certifi.where()`
    (`importer/places.py::_ssl_context()`). `certifi` viene ya instalado con `requests`.
    `requests` no sufre esto porque usa certifi por su cuenta; solo afecta a `urllib`.
18. **El EXIF de las fotos guarda la latitud en valor absoluto y el signo aparte.** Hay que
    escribir `GPSLatitudeRef=N|S` y `GPSLongitudeRef=E|W` además del número, o la foto
    acaba en el hemisferio equivocado. Para leer, el sufijo `#` en `-GPSLatitude#` pide el
    valor ya numérico con signo, en vez de `"3 deg 42' 0.00\" W"`. Y **los vídeos no usan
    nada de esto**: van con `QuickTime:GPSCoordinates` en un único campo de texto.
19. **Los GPX guardan la hora en UTC; las cámaras, hora local sin zona.** Cruzarlos
    directamente desplaza el track las horas que tenga el huso (2 h en España en verano),
    y las coincidencias salen mal sin dar ningún error. `importer/gpx.py` recibe el desfase
    y devuelve los puntos ya en hora local; por defecto usa el del sistema, y la interfaz
    lo deja ajustar para tracks grabados en otro huso.
20. **exiftool NO puede escribir en ficheros `.MTS`/`.M2TS`**: *"Writing of MTS files is
    not yet supported"*. Comprobado con un clip AVCHD real del usuario. No es una carencia
    pasajera de exiftool: el flujo de transporte AVCHD no tiene un sitio estándar donde
    meter metadatos. **Los MP4/MOV sí funcionan** — verificado escribiendo y releyendo un
    `.mp4` real de 212 MB. Por eso `geowrite.py::can_write()` lo comprueba *antes* de
    hacer la copia de seguridad (si no, dejaría un duplicado inútil de un archivo que va a
    fallar igual), los grupos exponen `unwritable`, y la interfaz avisa de que hay que
    convertir esos clips a MP4 primero. La conversión de la app es remuxeo sin pérdida, así
    que la salida existe y es barata.
21. **Las APIs de Synology se versionan por endpoint y el rango depende del DSM.**
    `SYNO.API.Auth` es la versión 6 en DSM 7 y la 3 en DSM 6, y en DSM 6 vive además en
    `auth.cgi` en vez de `entry.cgi`. Pedir una versión fuera de rango **no da un error
    claro**: devuelve un código genérico que parece un fallo de credenciales, que es la
    peor forma posible de fallar. Se resuelve consultando `SYNO.API.Info` por `query.cgi`
    (no necesita sesión) antes del login y quedándose con `min(maxVersion del NAS, la
    máxima que este código sabe manejar)`, más el `path` que devuelva. Está en
    `nas.py::_SynologySession.discover()`, con caída a los valores de DSM 7 si la consulta
    falla. Probado con respuestas simuladas de DSM 6 y DSM 7.
22. **En DSM 7 la carpeta personal de Synology Photos es `Photos`, en plural.** El
    `/homes/<usuario>/Photo` en singular era la de DSM 6 con Photo Station. La carpeta
    compartida sigue siendo `/photo` en ambos. La ayuda de la interfaz lo decía mal.
23. **Un código 2FA no se puede guardar en la configuración: caduca en 30 segundos.** Lo
    hacía (`nas.otp`), y era inútil: servía como mucho para el primer login. El mecanismo
    correcto de Synology es el **token de dispositivo**: al hacer login con `otp_code` +
    `enable_device_token=yes` + `device_name`, la respuesta trae un `did` que en los
    siguientes logins se manda como `device_id` y evita el segundo factor. Es lo mismo que
    la casilla "confiar en este dispositivo" de DSM, y se puede revocar desde
    Panel de control → Usuario → Avanzado. Implicaciones de diseño: el código se pide **en
    el momento** (no hay campo en el formulario), `NasOtpRequired` se distingue del resto
    de errores para que la interfaz sepa pedirlo, y `config.py::_migrate()` borra la clave
    `otp` de las configuraciones antiguas.
24. **Una subida en segundo plano no puede pedir un código 2FA.** Corre sin nadie mirando
    y el código caduca antes de que alguien lo vea. Por eso `nas_jobs.py` captura
    `NasOtpRequired` aparte y explica que hay que autorizar el equipo desde "Probar
    conexión"; los ficheros quedan pendientes y se reintentan después.
25. **Un Synology no tiene un `/` que listar.** La raíz son las *carpetas compartidas*, y
    se piden con `SYNO.FileStation.List` method=`list_share`, no con `list`. A partir de
    ahí ya se navega normal con `list` + `filetype=dir`. Está en `nas.py::list_folders()`.
26. **Los móviles no se conectan como disco: usan MTP o PTP.** Por eso el S25 no aparece
    en el Finder aunque Photos sí lo vea — macOS no lleva soporte MTP en el Finder, y
    Photos usa ImageCaptureCore, que habla PTP. **Detectarlos es trivial y sin
    dependencias**: `ioreg -p IOUSB -a -l` en formato plist filtrando por `idVendor`
    (`importer/phones.py`, 23 ms medidos con el S25 conectado). Leer su contenido es lo
    que necesitó todo lo que viene a continuación.
27. **PTP aplana las fotos; MTP muestra las carpetas.** Es la raíz del problema que llevó
    a construir esto: en modo PTP ("Transferencia de imágenes") el móvil expone sus fotos
    como una lista plana, mezclando `DCIM/Camera` con lo descargado de Telegram y de
    WhatsApp — que es exactamente lo que le pasaba al usuario en Captura de Imagen, y por
    lo que esa vía no le valía. En modo **MTP** ("Transferencia de archivos") aparece el
    árbol real. **El modo lo cambia el usuario en el móvil**, en la notificación USB; no
    hay forma de forzarlo desde el ordenador. Se nota en el PID: `0x6865` (PTP) →
    `0x6860` (MTP) en el Galaxy S25.
28. **Para reclamar la interfaz hay que MATAR `ptpcamerad`, no suspenderlo.** La interfaz
    MTP se anuncia con clase USB 6 (Still Image), así que macOS le adjudica `ptpcamerad`
    incluso en modo MTP, y gphoto2 falla con "Could not claim the USB device".
    `killall -STOP` **no sirve**: el proceso congelado conserva abierto su
    `AppleUSBHostInterfaceUserClient` y la interfaz sigue reclamada — se comprobó mirando
    `ioreg -c IOUSBHostDevice`, donde el UserClient seguía colgando de la interfaz. Al
    matarlo, el descriptor se cierra y funciona. `launchd` lo relanza solo; en MTP no
    vuelve de inmediato, que es la ventana que aprovecha esto, mientras que en PTP revive
    al instante y por eso ese modo es inservible. (Chrome también puede tener el
    dispositivo abierto por WebUSB, pero eso no bloqueó la interfaz.)
29. **Hay que usar los bindings de Python de gphoto2, no el ejecutable.** Cada invocación
    del programa renegocia la conexión MTP entera: **12-16 s por carpeta**, lo que hace la
    navegación inservible. Con una sesión abierta (`gp.Camera()` + `init()`), conectar
    cuesta **0,3 s** y listar una carpeta **0,00-0,05 s**. Medido sobre el S25.
30. **`gphoto2 --list-folders` es recursivo y aborta a medio camino.** Recorrer la raíz de
    un Android tarda ~15 s y se corta dentro de `Android/` (371 de 678 carpetas), que
    tiene cientos de carpetas de aplicaciones — así que `DCIM` nunca llegaba a aparecer.
    Además termina con código de salida 1 aunque los datos sean válidos. Por eso se navega
    **nivel a nivel y bajo demanda**, nunca el móvil entero.
31. **Contar los ficheros de una carpeta es caro; leer sus metadatos, gratis.** El primer
    `folder_list_files` de `DCIM/Camera` (3322 ficheros) tarda 13 s, pero deja la carpeta
    cacheada y a partir de ahí `file_get_info` de cada fichero es instantáneo: los 3322
    con tamaño y fecha salen en los mismos 13 s. Por eso `list_folder()` **no** cuenta los
    ficheros por defecto (navegar debe ser inmediato) y la interfaz ofrece "Ver los
    archivos de esta carpeta" como un paso aparte.
32. **El build de Docker pasa aunque la imagen esté rota.** El `Dockerfile` copia paquete
    a paquete (`COPY converter/`, `COPY static/`…), así que al añadir `importer/` había
    que añadir su `COPY`. Sin él, **el build termina con éxito** — solo copia ficheros, no
    ejecuta nada — el workflow publica la imagen en GHCR, y el fallo aparece al arrancar
    el contenedor: `ModuleNotFoundError: No module named 'importer'`. Pasó exactamente
    eso, y se detectó ejecutando la imagen, no mirando el workflow. **Al añadir un paquete
    nuevo, hay que tocar el Dockerfile**, y comprobarlo con
    `docker run --rm --entrypoint sh <imagen> -c "python -c 'import app'"`.
33. **La imagen de GHCR se publicaba solo para `linux/amd64`**, así que en un Mac con
    Apple Silicon ni siquiera se podía descargar (`no matching manifest for
    linux/arm64/v8`) y Watchtower no tenía forma de actualizar el contenedor allí. Ya se
    publica multi-arquitectura: una matriz construye cada plataforma en su **runner
    nativo** (`ubuntu-latest` y `ubuntu-24.04-arm`, gratis en repos públicos) publicando
    por digest, y un segundo job los une con `docker buildx imagetools create`. Se eligió
    runner nativo en vez de QEMU porque emular arm64 multiplica el tiempo de compilación.
    Detalle a recordar: la caché de Actions necesita `scope` por arquitectura, o una pisa
    a la otra en cada ejecución.
34. **`containrrr/watchtower` está abandonado y rompe con Docker moderno.** Su última
    imagen es de **noviembre de 2023**, y falla en bucle con `client version 1.25 is too
    old. Minimum supported API version is 1.40` — el contenedor se queda en
    `Restarting`, con lo que la actualización automática deja de funcionar en silencio.
    Hacer `docker pull` no arregla nada porque ya está al día. La alternativa mantenida
    es `nickfedor/watchtower` (1.21.0, Docker API v1.55), que acepta los mismos
    argumentos y se puede sustituir sin tocar nada más.
35. **`HOST=0.0.0.0` es imprescindible al probar el contenedor a mano.** `app.py` escucha
    en `127.0.0.1` por defecto, y sin esa variable el puerto publicado no responde desde
    fuera aunque el contenedor esté "Up". `docker-compose.yml` ya la pone; un `docker run`
    a pelo, no.
36. **Un `.command` abierto desde el Finder hereda un PATH mínimo**, y ahí se rompen dos
    cosas de golpe. El PATH que llega es
    `/usr/gnu/bin:/usr/local/bin:/bin:/usr/bin:.` — sin Homebrew y **sin `/usr/sbin`**:
    - `ffmpeg` y `exiftool` no se encuentran, y el lanzador antiguo cerraba la ventana
      diciendo que faltaban aunque estuvieran instalados.
    - **`diskutil` tampoco se encuentra**, y ese es el fallo peor porque es silencioso:
      `importer/sources.py` lo invocaba por nombre, saltaba `FileNotFoundError`, lo
      capturaba el `except` general de `_mounted_volumes()` y **las tarjetas de /Volumes
      desaparecían de la lista sin ningún aviso**. Solo pasaba al arrancar desde el
      Finder; desde una terminal funcionaba, que es lo que lo hace difícil de ver.

    Arreglado en dos sitios: el lanzador exporta el PATH completo, y `sources.py` llama a
    `/usr/sbin/diskutil` por ruta absoluta — **la app no debe depender de cómo la
    lancen**. Además, el fallo de `diskutil` ya no tumba la detección entera: se captura
    por volumen, de modo que la tarjeta aparece aunque no se puedan leer su tamaño ni si
    es extraíble.
37. **Docker no sirve en macOS para este proyecto.** Docker Desktop corre una VM Linux
    que no ve `/Volumes` ni los dispositivos USB del anfitrión, así que desde el
    contenedor **no se detecta ninguna tarjeta SD ni ningún móvil** — justo las dos
    entradas del módulo de Importación. El soporte Docker se mantiene porque vale para un
    NAS o un servidor, pero en el Mac del usuario la ejecución es **nativa**.
38. **Synology reutiliza los mismos códigos de error con significados distintos según la
    API**, y usar una sola tabla manda a diagnosticar el problema equivocado. Casos
    reales, con el mismo número:

    | Código | En `SYNO.API.Auth` | En `SYNO.FileStation.*` |
    |---|---|---|
    | 403 | Hace falta el código 2FA | Este usuario no puede hacer la operación |
    | 407 | **IP bloqueada** | **Operación no permitida** (sin permiso en la carpeta) |
    | 408 | Contraseña caducada | **No existe esa carpeta** |

    Le pasó al usuario: la app decía "El acceso está bloqueado desde esta IP" cuando el
    NAS respondía perfectamente y por web se entraba sin problema. El 407 venía de
    `SYNO.FileStation.List` sobre la carpeta remota, no del login. Ahora hay una tabla por
    familia (`_AUTH_ERRORS`, `_FILESTATION_ERRORS`, más `_COMMON_ERRORS` para los 1xx que
    sí son transversales) y `_syno_check()` recibe de qué API viene la respuesta. Además,
    `NasOtpRequired` solo se lanza desde el login: un 403 de File Station no es un 2FA.
    Y `test_connection()` distingue explícitamente "credenciales bien, carpeta mal", que
    es el caso que más despista.
39. **Para diagnosticar un NAS que "no va", `SYNO.API.Info` no necesita credenciales.**
    `https://<host>:5001/webapi/query.cgi?api=SYNO.API.Info&version=1&method=query&query=SYNO.API.Auth`
    responde sin sesión, así que separa en un segundo un problema de red o de puerto de
    uno de permisos — y sin arriesgarse a disparar el bloqueo automático de DSM con
    intentos de login fallidos. Comprobado contra el NAS del usuario: responde en 0,3 s y
    ofrece `SYNO.API.Auth` hasta la versión 7.
40. **El móvil tenía un paso intermedio que sobraba, y el usuario lo señaló.** La primera
    versión descargaba lo elegido a `~/.conversor-importador/descargas-movil/` y desde ahí
    se importaba, para reutilizar el flujo de las tarjetas sin tocarlo. Consecuencias, las
    tres reales: duplicaba el material en disco, **escondía los archivos** si no se
    completaba la importación en el momento (1,5 GB "desaparecidos" en una carpeta oculta,
    que fue exactamente lo que pasó), y obligaba a hacer el trabajo en dos tiempos.

    Se puede hacer directo porque **MTP da todo lo necesario sin descargar nada**:
    - el modelo del móvil (`camera.get_summary()` → `SM-S938B`), que es la clave de cámara
      y ya estaba en `KNOWN_MODELS`;
    - la fecha y el **tamaño exacto** de cada fichero, que es lo que hace falta para
      agrupar por día y planificar.

    `mtp_scan.py` construye con eso el mismo diccionario que `media.scan_source`, con
    rutas marcadas `mtp://`, y `jobs.py` descarga cada fichero directamente a su destino
    final. Un solo flujo para tarjeta y móvil. Lo único que no se sabe por adelantado es
    el GPS —vive dentro del archivo— así que se lee después de copiar, en un exiftool por
    lote (`_fill_missing_gps`). Y **del móvil no se borra nada**: sin checksum del lado
    del dispositivo la verificación es solo por tamaño, y eso no basta para destruir el
    único ejemplar.
41. **`--list-files` de una carpeta debe ser recursivo.** Pedir "los archivos de DCIM"
    tiene que traer los de `DCIM/Camera` y `DCIM/Screenshots`: en DCIM a secas no suele
    haber nada suelto, y una lista vacía ahí no le sirve a nadie. Medido en el S25: DCIM
    entero son 4070 archivos y 163 GB repartidos en **255 días**, lo que obligó a añadir
    un filtro por rango de fechas en la lista de días — marcar 255 casillas a mano no es
    una interfaz.
42. **En el upload multipart, DSM no lee el `_sid` del cuerpo: hay que ponerlo también en
    la query.** Síntoma desconcertante: el login va bien, `SYNO.FileStation.List` y
    `CreateFolder` funcionan (POST normal, `_sid` en el cuerpo), y justo la subida
    responde **119 «SID not found»** un instante después. Se arregla pasando
    `params={"_sid": ...}` en la petición de subida. De paso se guarda la cookie `id` de
    sesión, que cubre las rutas de DSM que identifican por cookie.

    Añadido a eso, ante 105/106/119 la sesión se rehace una vez y se reintenta el fichero:
    una subida de cientos de fotos puede agotar la sesión por el camino, y no tiene
    sentido perder todo lo que quedaba. El token de dispositivo hace que ese relogin no
    pida 2FA, que en un job en segundo plano no habría a quién pedírselo.
43. **Las miniaturas del móvil salen del propio móvil.** MTP guarda una previsualización
    de cada foto: `GP_FILE_TYPE_PREVIEW` devuelve **37 KB en 0,03 s** frente a los 2 MB
    de la foto entera, lo que hace viable la vista rápida sobre un origen MTP sin
    descargar nada. Se cachean en disco como las demás
    (`thumbs.py::get_phone_thumbnail`), así que solo se piden una vez.
44. **El mismo móvil Samsung se identifica de dos formas distintas.** Las fotos llevan el
    nombre comercial en EXIF (`Galaxy S25 Ultra`) y los vídeos el código interno en un tag
    propio del fabricante (`Samsung:SamsungModel` = `SM-S938B`), que además no se leía, de
    modo que los vídeos del móvil caían en "sin identificar" mientras sus fotos de la
    misma tarde sí se agrupaban. Ahora se lee ese tag y **ambas formas están en
    `KNOWN_MODELS` apuntando al mismo nombre de carpeta**.

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

Y dentro de la **carpeta de destino de las importaciones** (la biblioteca de fotos):

| Ruta | Contenido | Módulo |
|---|---|---|
| `.ubicaciones.json` | Qué archivo tiene GPS y cuál no, con rutas relativas | `geoindex.py` |
| `*/_originales_sin_gps/` | Copia intacta previa a escribir el GPS en el archivo | `geowrite.py` |

`_originales_sin_gps/` es la única carpeta generada que **no** es caché regenerable: es lo
único que permite deshacer una asignación de ubicación equivocada. Borrarla es seguro solo
si se dan por buenas todas las ubicaciones ya escritas. El escaneo la ignora
(`geoindex.rebuild()` la salta) para que sus fotos no cuenten como parte de la biblioteca.

El importador es la excepción: su estado es **global**, no por carpeta de proyecto, y
vive en `~/.conversor-importador/`:

| Fichero | Contenido |
|---|---|
| `config.json` | Destino, mapeo de cámaras aprendido, ajustes del NAS. **Permisos 0600** porque guarda la contraseña del NAS y el token 2FA en claro; nunca se devuelven al navegador (`public_config()`) |
| `descargas-movil/` | Carpetas de trabajo con lo bajado del móvil, una por descarga. Se borran al importarlas (`mtp_jobs.cleanup()`, que solo borra dentro de aquí) |
| `historial.json` | Qué se importó (para detectar duplicados y saber qué falta por subir al NAS) y las últimas 50 importaciones |
| `miniaturas/` | Miniaturas del contenido de las tarjetas |

Las miniaturas se cachean **fuera de la tarjeta** a propósito: puede estar protegida
contra escritura o desaparecer en cualquier momento, y no conviene escribir nada en ella
antes de haber copiado.

Ninguna de estas carpetas tiene límite de tamaño ni expiración — si en el futuro se
usa la app con muchos clips durante mucho tiempo, podría valer la pena añadir una
forma de purgar cachés antiguas. No implementado, no pedido todavía.

## Rutas Flask (API completa)

```
GET  /importacion                   Página de Importación
GET  /ubicacion                     Página de Ubicación
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

GET|POST /api/importacion/config     Configuración global (POST sin contraseña = no la cambia)
GET  /api/importacion/sources        Detectar orígenes (?retry=1 reintenta carpetas bloqueadas)
POST /api/importacion/scan           Escanear un origen -> scan_id + cámaras + ficheros
POST /api/importacion/plan           Plan de destino (previsualización, no toca disco)
POST /api/importacion/start          Lanzar la importación
GET  /api/importacion/status/<job_id>
GET  /api/importacion/thumb?path=    Miniatura de un fichero del origen
GET  /api/importacion/history        Últimas importaciones + pendientes de subir
POST /api/importacion/nas-test       Probar la conexión con el NAS
POST /api/importacion/nas-upload     Subir lo que quedó pendiente
GET  /api/importacion/nas-status/<job_id>
POST /api/importacion/nas-browse     Listar carpetas del NAS (path vacío = compartidas)
POST /api/importacion/nas-mkdir      Crear carpeta en el NAS
POST /api/importacion/nas-forget-device   Olvidar el token 2FA de este equipo
GET  /api/importacion/phones         Móviles conectados por USB (+ cuáles se pueden leer)
POST /api/importacion/open-transfer-app   Abrir Captura de Imagen (macOS)
POST /api/importacion/mtp/folder     Listar subcarpetas del móvil (sin contar ficheros)
POST /api/importacion/mtp/files      Listar ficheros de una carpeta, con fecha y tamaño
POST /api/importacion/mtp/download   Descargar la selección a una carpeta de trabajo
GET  /api/importacion/mtp/status/<job_id>
GET  /api/importacion/mtp/pending    Descargas que quedaron sin importar
POST /api/importacion/mtp/cleanup    Borrar una carpeta de descarga ya importada

POST /api/ubicacion/groups           Cargar índice y agrupar en sesiones (gap_minutes)
POST /api/ubicacion/reindex          Reconstruir el índice (full=1 relee todo)
POST /api/ubicacion/match            Cruzar sesiones con referencias (índice/carpeta/GPX)
POST /api/ubicacion/assign           Lanzar escritura de GPS en los archivos
GET  /api/ubicacion/assign-status/<job_id>   (también sirve para el job de reindex)
POST /api/ubicacion/restore          Deshacer: restaurar los originales sin GPS
GET  /api/ubicacion/search?q=        Buscar lugar (Nominatim, 1 req/s)
GET  /api/ubicacion/reverse?lat=&lon=   Nombre del sitio a partir de coordenadas
POST /api/ubicacion/pick-gpx         Selector nativo macOS (fichero .gpx)
```

Las miniaturas de Ubicación reutilizan `/api/importacion/thumb`: sirve cualquier ruta
absoluta, y no había razón para duplicar la caché.

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
   así se detectó el bug del decorador roto, y también el de que el escaneo leía el GPS
   pero `app.py` no lo incluía en la respuesta al navegador.
4. Para probar Ubicación hace falta material con GPS, y ninguna de las cámaras del
   usuario lo pone. Se fabrica con exiftool sobre copias en el scratchpad:
   ```
   exiftool -overwrite_original -GPSLatitude=37.1773 -GPSLatitudeRef=N \
            -GPSLongitude=-3.5986 -GPSLongitudeRef=W foto.JPG
   ```
   Y para las sesiones, forzando horas separadas con
   `-DateTimeOriginal="2026:08:20 09:00:00" -CreateDate=...`. Así se comprobó que tres
   ráfagas (09:00, 11:30, 17:00) dan tres sesiones con corte de 1 h.

## Pendiente (explícitamente aplazado, no implementado)

- **El envío al NAS no se ha probado contra un NAS real.** Toda la lógica local está
  verificada (formulario, guardado, saneado de credenciales, mensajes de error de
  conexión, negociación de versión de API con DSM 6 y 7 simulados), pero no ha habido un
  Synology delante.

  **El usuario tiene DSM 7.4 en todos sus NAS**, así que la duda de la versión de
  `SYNO.API.Auth` ya no aplica: en DSM 7 es la 6, que es la que se usa. Además ahora se
  negocia automáticamente contra `SYNO.API.Info` (ver "Hallazgos" #21), con lo que deja de
  ser un punto de fallo en cualquier DSM.

  El login con 2FA, el token de dispositivo y el explorador de carpetas remotas **sí están
  probados de extremo a extremo**, contra un DSM de mentira que replica las respuestas de
  la API (`scratchpad/fake_dsm.py` en la sesión que lo escribió; se regenera fácil a partir
  de "Hallazgos" #23 y #25). Eso cubre el flujo y los errores, pero no el comportamiento
  del Synology de verdad.

  Lo que queda por comprobar la primera vez que haya un NAS delante:
  - Que `SYNO.FileStation.Upload` acepta el multipart tal como se construye en
    `nas.py::_SynologySession.upload()`. El binario debe ir en la última parte; eso sí
    está confirmado por la documentación oficial de Synology, pero no probado en vivo.
  - Que la cuenta tiene permiso de escritura en la carpeta destino y que Synology Photos
    reindexa lo subido por File Station (debería: es una carpeta que ya vigila).
  - Que el token de dispositivo real de DSM sobrevive entre sesiones como se espera.
- **Fase 2**: formatos `.avi`, `.mkv`, `.wmv`, `.3gp` — se listan en el escaneo bajo
  "Otros formatos" pero no se procesan. No probados, podrían tener códecs que ffmpeg
  no maneje igual de bien que H.264/MP4.
- No hay suite de tests automatizados — todo verificado manualmente/con scripts ad
  hoc contra clips reales durante el desarrollo.
- No hay purga/expiración de las carpetas de caché (`stabilization_data/`,
  `.proxies/`, `.miniaturas/`, `~/.conversor-importador/miniaturas/`) — crecen sin
  límite. El `historial.json` del importador tampoco se poda nunca (los `runs` sí, a 50).
- El zoom automático de la vista previa en canvas es una aproximación (ver
  "Hallazgos" #2) — si en algún momento se nota muy desviado del resultado real,
  revisar `autoZoomPercent()` en `static/stabilize_preview.js`.
- **Sin límite de tamaño en `_originales_sin_gps/`.** Si se asignan ubicaciones a una
  biblioteca grande, duplica esos archivos. No hay purga ni aviso de cuánto ocupa; sería
  lo primero que añadir si molesta.
- **Los `.MTS`/`.M2TS` no pueden llevar ubicación** (ver "Hallazgos" sobre exiftool y
  AVCHD). Está manejado con un aviso claro, pero significa que una sesión con clips AVCHD
  sin convertir nunca queda del todo resuelta. Lo natural sería encadenar: detectar los
  MTS de una sesión, convertirlos con Conversión y ubicar el MP4 resultante, todo desde
  Ubicación. No implementado, no pedido.
