# Conversor de vídeo

Aplicación web (Flask, en local) para el flujo de trabajo completo de vídeo de cámara —
AVCHD `.MTS`/`.M2TS` y `.mp4`/`.mov` (incluido 4K) — organizada como un editor con
**seis módulos** en una barra lateral persistente, cada uno con su propia carpeta de
proyecto (se recuerda al cambiar de sección):

- **💾 Importación** — vuelca tarjetas de cámara al disco organizadas por cámara y día,
  y las envía al NAS.
- **📍 Ubicación** — agrupa lo importado por sesiones y pone coordenadas GPS a las fotos
  y vídeos que no las traen.
- **📼 Conversión** — remuxeo sin pérdida y renombrado por fecha de captura.
- **🗜️ Recompresión** — para formatos que no admiten remuxeo, o para reducir el tamaño
  de un clip ya convertido (compartir por WhatsApp/email, etc.).
- **🩹 Estabilización** — corrige el temblor de cámara, con modo automático o
  personalizado.
- **🎬 Montaje** — mini editor: unir clips, recortar, títulos, transiciones,
  estabilización integrada con vista previa, y exportación final.

Pensado para que el resultado se reproduzca sin problemas al subirlo a un NAS (Synology
Photos, Plex, Emby, etc.) y se vea bien tanto en el móvil como en la TV.

## Funciones

- **Importación de tarjetas**: detecta la tarjeta insertada (o una carpeta ya copiada al
  Escritorio, que se trata igual), identifica la cámara por sus metadatos, y copia todo a
  una carpeta local ordenada por cámara y por día, separando JPG de RAW y dejando los
  vídeos aparte. Verifica cada copia por checksum, puede borrar la tarjeta solo tras
  comprobarla, evita recopiar lo ya importado, y sube el resultado al NAS.
- **Ubicación GPS**: marca qué fotos traen coordenadas y cuáles no, las agrupa en sesiones
  por cercanía en el tiempo, y deduce la posición de las que faltan cruzándolas con las
  fotos del móvil o con un track GPX. Lo que no se pueda deducir se elige a mano sobre un
  mapa de OpenStreetMap con buscador.
- **Remuxeo sin pérdida** (Conversión): copia el vídeo H.264 bit a bit, solo cambia el
  contenedor a `.mp4` — vale tanto para AVCHD (`.MTS`/`.M2TS`) como para cámaras que ya
  graban en `.mp4`/`.mov` (incluido 4K), cuyo audio (a menudo PCM sin comprimir) puede
  necesitar el mismo recodificado opcional a AAC que el AC-3 de AVCHD. No hay
  recompresión ni pérdida de calidad de vídeo en ningún caso.
- **Recompresión**: recodifica de verdad (a diferencia del remuxeo) formatos que no
  admiten copia sin pérdida (`.avi`, `.mkv`, `.wmv`, `.3gp`), o reduce el tamaño de
  cualquier clip ya convertido/estabilizado con preset de calidad y tope de resolución.
- **Renombrado por fecha de captura**: tanto vídeos como fotos se renombran a
  `AAAAMMDD_HHMMSS.ext` usando la fecha real leída de los metadatos (con `exiftool`),
  no la fecha de copia del archivo.
- **Estabilización** (independiente del remuxeo): corrige el temblor de cámara con
  `vid.stab` (dos pasadas: detección + corrección), con modo automático o personalizado
  (sensibilidad, suavizado, zoom fijo/dinámico/manual). Esto sí recodifica el vídeo —
  es inevitable para poder corregirlo.
- **Montaje**: mini editor para unir clips ya convertidos, recortarlos, añadir títulos
  (texto o imagen con transparencia), transiciones cruzadas, y estabilización integrada
  con vista previa instantánea en el navegador — guardando el trabajo como proyecto
  para continuarlo más tarde.
- **Explorador de carpetas nativo**: botón "Explorar…" que abre el selector de carpetas
  de macOS (Finder), además de un navegador de carpetas dentro de la propia página. La
  última carpeta usada se recuerda al cambiar de módulo.
- No se modifican ni se borran los archivos originales en ningún momento.

## Requisitos

- macOS (usa AppleScript para el selector de carpetas nativo y, opcionalmente,
  VideoToolbox para la estabilización acelerada por hardware).
- Python 3.10+
- [ffmpeg-full](https://ffmpeg.org/) (necesario para la estabilización y para el
  Montaje — incluye `libvidstab` y `libfreetype`/`libfontconfig` para los títulos) y
  [exiftool](https://exiftool.org/):

  ```bash
  brew install ffmpeg ffmpeg-full exiftool
  ```

  `ffmpeg-full` se instala aparte de `ffmpeg` sin pisarlo (queda "keg-only"); la app lo
  busca automáticamente en `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` cuando lo necesita.
  Si solo vas a usar el remuxeo (sin estabilizar ni montar), basta con `ffmpeg` normal.

## Instalación

```bash
git clone https://github.com/ma-ochoa/conversor-avchd.git
cd conversor-avchd
pip3 install -r requirements.txt
```

`requests` y `paramiko` solo hacen falta para enviar al NAS (File Station y SFTP
respectivamente). Todo lo demás funciona sin ellos.

## Arranque

**Opción rápida (macOS)**: haz doble clic en `Iniciar Conversor AVCHD.command` — arranca
el servidor y abre el navegador automáticamente.

**Desde terminal**:

```bash
python3 app.py
```

Y abre http://127.0.0.1:5050 (el servidor solo escucha en local, no es accesible desde
otros equipos de la red).

## Despliegue con Docker

Alternativa a instalar Python/ffmpeg-full a mano — la imagen incluye ya todo lo
necesario (el `ffmpeg` de Debian trae `libvidstab`/`libfreetype` de serie, a
diferencia de macOS donde hace falta el paquete aparte `ffmpeg-full`).

```bash
cp .env.example .env      # edita MEDIA_DIR con la carpeta que quieras poder explorar
docker compose up -d --build
```

Abre http://localhost:5050. La carpeta indicada en `MEDIA_DIR` queda montada dentro
del contenedor en `/data` — es la carpeta de origen que verás por defecto en cada
página, y desde ahí puedes navegar a cualquier subcarpeta. Todo lo que la app genera
(`conversion/`, los vídeos `_stabilized.mp4`, etc.) se escribe dentro de esa misma
carpeta montada, así que queda en tu Mac igual que con la instalación nativa — nada se
pierde si el contenedor se reinicia.

**Diferencias frente a la instalación nativa**:

- El botón **"Explorar…"** (selector nativo de macOS) no funciona dentro del
  contenedor — usa el navegador de carpetas propio de la página (escribe la ruta,
  p. ej. `/data/DCIM`, y pulsa "Ir").
- El **modo rápido (VideoToolbox)** de Estabilización no tiene efecto — no hay
  aceleración por hardware dentro de un contenedor Linux; usa siempre software
  (misma calidad que sin marcar la casilla en la instalación nativa).
- La carpeta de trabajo configurada en **⚙️ Ajustes** (ver más abajo) se guarda dentro
  del propio volumen montado (`/data/.conversor-avchd/config.json`), así que persiste
  igual que el resto — pero la ruta que elijas ahí debe ser una ruta **dentro** de
  `/data` (p. ej. `/data/mi_libreria`), no una ruta del Mac anfitrión.

**Actualización automática**: `docker-compose.yml` etiqueta el contenedor con
`com.centurylinklabs.watchtower.enable=true`. Cada push a `main` dispara
`.github/workflows/docker-publish.yml`, que publica la imagen en
`ghcr.io/ma-ochoa/conversor-avchd`; un [Watchtower](https://containrrr.dev/watchtower/)
en marcha (compartido o propio, con `--label-enable`) la detecta, la descarga y
recrea el contenedor solo, sin ningún paso manual.

## Importación

Es el paso previo a todo lo demás: pasar el material de la tarjeta al disco, ya ordenado.

### 1. Origen

**Detectar tarjetas** busca tarjetas insertadas y también carpetas del Escritorio o de
Descargas que parezcan un volcado manual — una carpeta que copiaste tú a mano se trata
exactamente igual que una tarjeta. Si no aparece lo que buscas, **Elegir una carpeta…**
sirve para cualquier ruta.

> En macOS, la primera vez el sistema pedirá permiso para leer el Escritorio y Descargas.
> Hasta que se conceda (Ajustes del Sistema → Privacidad y seguridad → Archivos y
> carpetas), esas dos carpetas no se listan y la app lo avisa en pantalla. «Elegir una
> carpeta…» funciona igualmente.

### 2. Qué hay en el origen

La app lee los metadatos de todo el contenido e identifica **cada cámara por su modelo
EXIF**, proponiendo un nombre de carpeta (`ILCE-6400` → `Sony A6400`). Puedes cambiarlo:
queda recordado y la próxima vez que uses esa cámara ya saldrá elegido.

El contenido se agrupa **por día**, y cada día tiene su casilla para incluirlo o no y un
campo para el **nombre del evento**. Si lo rellenas, la carpeta pasa a ser
`2026-08-09 - Concierto` en vez de solo `2026-08-09`.

### 3. Vista rápida

Cuadrícula de miniaturas de todo lo que hay en la tarjeta, incluidos los RAW (se extrae
la previsualización que llevan dentro) y los vídeos. Se generan según van apareciendo en
pantalla y se guardan fuera de la tarjeta, que no se toca. Lo que ya se importó antes
aparece atenuado y marcado.

**Móviles conectados**: si enchufas un Android o un iPhone se detecta, y **Explorar el
móvil** abre sus carpetas para elegir qué bajar: entras en `DCIM/Camera` y dejas fuera lo
descargado de Telegram, WhatsApp o las capturas de pantalla. Verás los archivos con su
fecha y tamaño, puedes acotar por rango de fechas y omitir lo que ya importaste otra vez.
Lo que descargues pasa al flujo normal: se organiza por cámara, día y evento igual que una
tarjeta.

> **El móvil tiene que estar en modo «Transferencia de archivos» (MTP).** Con el cable
> puesto, baja la barra de notificaciones del móvil, toca la notificación del USB y elige
> esa opción. En el otro modo, «Transferencia de imágenes (PTP)», el móvil **no muestra
> carpetas**: entrega todas las fotos en una lista plana con la cámara mezclada con
> Telegram y WhatsApp — que es justamente lo que hace inservible a Captura de Imagen para
> esto. Además, en PTP macOS reserva el móvil para sí y la app no puede leerlo.

Necesita gphoto2, que se instala aparte:

```bash
brew install libgphoto2 && pip install gphoto2
```

Sin él, el móvil se sigue detectando y se ofrece abrir **Captura de Imagen** para volcar a
una carpeta, que luego se detecta aquí como si fuera una tarjeta.

**Filtrar por día**: pulsando la fecha en el paso anterior (o eligiéndola en el desplegable
«Día») la cuadrícula muestra solo ese día, y aparece un campo para escribir el nombre del
evento sin salir de aquí — la idea es mirar las fotos y decidir con ellas delante cómo se
va a llamar la carpeta. Es el mismo dato que el campo del paso 2: se sincronizan.

**Indicador de ubicación**: cada miniatura lleva un 📍 en la esquina. En color si la foto
trae coordenadas GPS; en gris y tachado en rojo si no. El recuento por día y el total
aparecen también en los resúmenes. Esa información se guarda en un fichero
`.ubicaciones.json` dentro de la carpeta de destino, que es de donde parte el módulo
Ubicación.

### 4. Destino y opciones

La estructura que se crea es:

```
<destino>/
  Fotos/Sony A6400/2026-08-09 - Concierto/JPG/20260809_224512.JPG
  Fotos/Sony A6400/2026-08-09 - Concierto/RAW/20260809_224512.ARW
  Videos/Sony A6400/20260809_231004.MP4
```

- **Renombrar por fecha de captura** — igual que en Conversión. Un RAW y su JPG siempre
  reciben el mismo nombre base aunque acaben en carpetas distintas, así que siguen
  emparejados. Se puede desactivar para conservar los nombres de la cámara.
- **Agrupar también los vídeos por día** — por defecto los vídeos van directos a
  `Videos/<cámara>/`, sin subcarpeta de día.
- **Omitir lo ya importado antes** — si reinsertas la misma tarjeta, no se vuelve a copiar
  nada. La comparación es por nombre, tamaño y momento exacto de captura.
- **Verificar cada copia por checksum (SHA-256)** — relee lo copiado y lo compara con el
  original.
- **Borrar del origen una vez copiado y verificado** — solo se borra lo que se ha copiado
  *y* verificado. Si falla un solo archivo, no se borra nada. Requiere la verificación
  activada; sin ella la app se niega a borrar.
- **Enviar al NAS al terminar** — encadena la subida a la importación.

**Ver cómo quedará** muestra el árbol de carpetas exacto antes de copiar nada, y comprueba
que hay espacio libre suficiente en el destino.

### 5. Envío al NAS

Synology **no publica una API de Synology Photos para aplicaciones de terceros**, así que
la app usa **File Station**, que sí está documentada oficialmente por Synology: sube los
archivos a la carpeta que Photos ya tiene indexada y Photos los indexa por su cuenta. Va
por HTTPS con la cuenta de DSM y no hace falta activar el servicio FTP.

En DSM 7 la carpeta es `/photo` (espacio compartido) o `/homes/<usuario>/Photos` (espacio
personal, en plural). Como alternativa hay **SFTP** y **FTP/FTPS**, para NAS que no sean
Synology.

**Verificación en dos pasos.** Si la cuenta la tiene activada, al pulsar *Probar conexión*
se te pide el código **en ese momento** — no se guarda, porque caduca en 30 segundos. Lo
que sí se guarda es la autorización que devuelve el NAS a cambio, de forma que este equipo
queda registrado como de confianza y no vuelve a pedírtelo. *Olvidar este equipo* la borra
de aquí; para revocarla también en el NAS, quítala en DSM → Panel de control → Usuario →
Avanzado.

**Elegir la carpeta remota.** *Explorar…* abre un navegador de las carpetas del NAS: se
empieza por las carpetas compartidas, se entra pinchando, hay un filtro por nombre y se
pueden **crear carpetas nuevas** sin salir de ahí.

Si una subida se corta a mitad, **Subir pendientes al NAS** reintenta solo lo que quedó
sin subir, sin repetir la importación.

> La contraseña se guarda en `~/.conversor-importador/config.json` con permisos de solo
> lectura para tu usuario, y nunca se devuelve al navegador.

## Ubicación

Las cámaras sin GPS (la mayoría de réflex y sin espejo) no guardan dónde se tomó la foto,
así que Synology Photos no las coloca en el mapa. Este módulo lo arregla después de la
importación, apoyándose en el móvil, que sí lo guarda.

### 1. Carpeta de la biblioteca

La carpeta donde importas. Se lee el `.ubicaciones.json` que dejó la importación; si la
carpeta viene de antes de que existiera este módulo, **Buscar archivos nuevos** lo
construye leyendo el EXIF de todo. **Releer todo de cero** rehace el índice entero, para
cuando se ha quedado desfasado.

### 2. Sesiones detectadas

Las fotos se agrupan en **sesiones por cercanía en el tiempo**, no solo por día: la
secuencia que empieza a las 9:00 es una sesión, y si vuelves a disparar a las 11:00 eso ya
es otra. El corte por defecto es una hora sin disparar, ajustable en pantalla.

No se separa por cámara a propósito: si la cámara y el móvil disparan a la vez en el mismo
sitio, caen en la misma sesión, que es justo lo que permite usar la posición del móvil para
la cámara.

Cada sesión muestra su franja horaria, cuántos archivos tiene con y sin ubicación, unas
miniaturas para reconocerla, y un borde verde o rojo según esté resuelta. **Se pueden
marcar varias sesiones a la vez** para asignarles la misma ubicación de una tacada.

### 3. Deducir ubicación desde referencias

Para cada sesión sin ubicación busca una referencia con GPS tomada a una hora cercana y
propone su posición. Las referencias pueden venir de tres sitios, combinables:

- **Las fotos que ya importaste y sí tienen GPS** — las del móvil, típicamente.
- **Una carpeta cualquiera con fotos del móvil**, sin importarlas ni copiarlas: solo se
  leen sus metadatos.
- **Un track GPX** de un reloj, un móvil o un registrador. Da cobertura continua, así que
  es lo más preciso.

Cada propuesta dice de dónde salió y **con cuánta diferencia de tiempo** se dedujo, porque
es una aproximación, no una medición. Si la sesión ya tenía alguna foto con GPS y la
propuesta cae lejos de ella, se avisa en rojo.

> **Sobre la hora del GPX**: los tracks guardan la hora en UTC y las cámaras la hora local
> sin indicar zona. El campo «Desfase horario» viene con el de tu sistema; ajústalo si el
> track se grabó en otro huso, o el track quedará desplazado varias horas.

### 4. Asignar ubicación

Lo que no se pueda deducir se elige a mano: busca un sitio por nombre (Plaza Nueva,
Granada) o pincha directamente en el mapa. Los puntos grises son las sesiones que ya tienen
posición; el rojo es la que estás eligiendo.

**La ubicación se escribe dentro del archivo** (EXIF en fotos, metadatos del contenedor en
vídeos), porque es lo único que Synology Photos lee. Es la única parte de toda la app que
modifica los archivos originales, así que por defecto guarda una copia intacta en una
subcarpeta `_originales_sin_gps/` y **Deshacer en las marcadas** la restaura.

Tras escribir, cada archivo se relee para confirmar que la posición quedó realmente dentro:
solo entonces se anota en el índice.

> **Los clips AVCHD (`.MTS`) no admiten ubicación.** No es una limitación de la app: el
> formato no tiene dónde guardar metadatos, y ninguna herramienta puede escribirlos. Las
> sesiones que los contengan lo avisan en rojo. La solución es convertirlos a MP4 en el
> módulo de **Conversión** (que es remuxeo sin pérdida, no recomprime) y asignar la
> ubicación al MP4 resultante. Los MP4 y MOV sí funcionan con normalidad.

## Conversión

### 1. Elegir la carpeta de origen

Escribe la ruta directamente, navega con la lista de carpetas, o pulsa **📁 Explorar…**
para usar el selector nativo de macOS. Debe ser una carpeta que contenga (en cualquier
subcarpeta) la estructura `AVCHD/BDMV/STREAM` de la cámara, o los `.mp4`/`.mov` de una
tarjeta SD (por ejemplo la carpeta `PRIVATE/M4ROOT/CLIP` de una cámara Sony) — por
ejemplo, la tarjeta SD montada tal cual, o una copia de esas carpetas.

### 2. Escanear

Pulsa **Escanear esta carpeta**. La app busca de forma recursiva:

- **Vídeos** (`.MTS`, `.M2TS`, `.mp4`, `.mov`, `.m4v` — incluido 4K) — con su fecha de
  captura y el nombre que tendrán al convertir.
- **Fotos** (`.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`, `.tif`, `.tiff`) — mismo criterio
  de fecha/renombrado, sin conversión (se copian tal cual).
- **Otros formatos** (`.avi`, `.mkv`, `.wmv`, `.3gp`) — no admiten remuxeo sin pérdida;
  se listan aquí de forma informativa, pero se procesan desde **🗜️ Recompresión**.

### 3. Convertir

Marca los clips/fotos que quieras (checkbox en la cabecera de cada tabla para
marcar/desmarcar todos de golpe) y pulsa **Convertir seleccionados**. El resultado se
guarda en una carpeta `conversion/` — dentro de la carpeta de origen por defecto, o en
la carpeta de trabajo configurada en **⚙️ Ajustes** si has fijado una (ver más abajo) —
lista para subir al NAS. Si el audio del vídeo no se oye en el navegador o el móvil
(AC-3 en AVCHD, o PCM sin comprimir en muchas cámaras que graban directamente en
`.mp4`/`.mov`), marca **"Recodificar audio a AAC si no es compatible"** — solo afecta
al audio, el vídeo se sigue copiando sin recomprimir en cualquier caso.

**Prefijo del nombre** (opcional): antepone un texto fijo al nombre por fecha, p. ej.
`a6400_20260815_200015.jpg` — útil para poder distinguir de qué cámara/fuente viene
cada fichero una vez que varias fuentes conviven en la misma carpeta de salida. La
columna "Destino" se actualiza al momento según lo escribes.

Las conversiones ya hechas se recuerdan (`conversion/.manifest.json`): puedes reescanear
la misma carpeta tras grabar más clips sin reconvertir lo ya hecho, salvo que actives
**"Forzar reconversión"**.

## Recompresión

Para dos casos que el remuxeo sin pérdida no puede resolver:

- **Formatos no soportados**: cualquier `.avi`/`.mkv`/`.wmv`/`.3gp` detectado al escanear
  la carpeta aparece aquí para recodificarlo de verdad a MP4/H.264/AAC.
- **Reducir tamaño**: elige cualquier clip ya convertido o estabilizado (se listan con
  su origen) para generar una copia más ligera — pensado para compartir por WhatsApp,
  email, etc. La copia original nunca se toca.

Controles: **Calidad** (alta/media/baja, controla el CRF de `libx264`) y **Resolución
máxima** (original/1080p/720p/480p — nunca amplía un vídeo más pequeño que el tope
elegido). El resultado se guarda en `recompresion/` (dentro de la carpeta de origen, o
de la carpeta de trabajo si has configurado una en **⚙️ Ajustes**), con el mismo
renombrado por fecha que el resto de la app, y muestra cuánto se ha reducido el tamaño
(p. ej. "72.4 MB → 3.8 MB (-94.8%)").

## Estabilización

En la tabla de vídeos hay una columna **"Estabilizar"** — marca los clips con temblor
de cámara y pulsa **Estabilizar marcados**. El resultado se guarda **junto al vídeo
original**, como `<nombre>_stabilized.mp4` (o en la misma ruta relativa dentro de la
carpeta de trabajo, si has configurado una — ver **⚙️ Ajustes**), y muestra
estadísticas de cuánto ha tenido que corregir:

> **Aviso sobre 4K**: la estabilización analiza y corrige a la resolución original del
> vídeo — es lo que garantiza que la corrección sea correcta (reducir la resolución solo
> para analizar más rápido da una corrección más débil de lo que parece, lo comprobé
> antes de descartarlo). En 4K esto es bastante más lento que en 1080p (varias veces más
> lento, no proporcional al tamaño del archivo sino a los píxeles por fotograma) — cuenta
> con que un clip 4K de varios minutos puede tardar bastante más que uno equivalente en
> 1080p. El remuxeo (convertir, sin estabilizar) no tiene este problema: es igual de
> rápido en 4K que en cualquier otra resolución, porque no recodifica.

- **Recorte/zoom**: cuánto ha tenido que ampliar y recortar el fotograma para tapar los
  bordes que deja la corrección — es la medida de cuánto encuadre se "pierde". Cuanto
  más tiembla el vídeo, más alto es este número.
- **Confianza de seguimiento**: en cuántos fotogramas ha tenido información fiable para
  detectar el movimiento (poca luz o poco contraste hacen que falle más).

También se recuerda lo ya estabilizado (comprobando si ya existe el
`<nombre>_stabilized.mp4`), con la misma opción de forzar.

**Automático vs. personalizado**: los controles están siempre visibles, pero
bloqueados (en gris) mientras esté marcado "Automático" — así ves de un vistazo qué
valores de fábrica se van a usar. Marca **"Personalizado"** para poder tocarlos:

- **Sensibilidad al temblor**: cuánto asume el análisis que tiembla la cámara.
- **Suavizado**: cuántos fotogramas se usan para suavizar el movimiento — más alto da un
  resultado más "flotante", pero necesita más recorte.
- **Zoom/recorte**: automático (fijo para todo el vídeo), automático dinámico (varía
  según haga falta en cada momento) o **manual** — tú eliges el porcentaje exacto de
  zoom, igual que el control de Pinnacle.

Debajo hay un grupo plegable **"Avanzado"** con parámetros de `vid.stab` que casi
nunca hace falta tocar en vídeo doméstico, cada uno con su explicación: precisión del
análisis, paso de búsqueda, contraste mínimo, interpolación, algoritmo de suavizado, y
topes máximos de desplazamiento/rotación por fotograma. Se comportan igual que los
básicos — bloqueados en automático, editables en personalizado.

El análisis (la parte lenta) se cachea por clip (junto al propio vídeo, en
`stabilization_data/`): si solo cambias el suavizado, el zoom, o cualquiera de los
parámetros "avanzados" de la pasada de corrección y vuelves a procesar el mismo clip,
no hace falta repetirlo. Cambiar la sensibilidad al temblor, la precisión, el paso de
búsqueda o el contraste mínimo sí invalida la caché y repite el análisis (todos
afectan a la propia detección del movimiento, no solo a cómo se corrige después).

### Analizar y ajustar un clip antes de recomprimir

Cada fila de la tabla tiene un botón **"🔍 Analizar y ajustar"** que abre una
previsualización del clip en el navegador — mueves los sliders de suavizado/zoom y ves
al instante una aproximación del resultado, **sin generar ningún vídeo nuevo**. Si el
clip ya se había analizado antes con estos mismos parámetros, la previsualización se
carga sola nada más abrir el modal, sin tener que pulsar "Analizar clip" otra vez.
Cuando el ajuste te convence, **"Guardar ajuste"** lo deja guardado para ese clip
(puedes volver más tarde, probar otra cosa, y guardar o **"Descartar ajuste
guardado"** sin que eso afecte a si el clip está o no ya estabilizado en disco).

La columna "Estado" refleja esto por clip:

- **—**: sin analizar.
- **🔍 analizado**: ya se ha calculado el análisis (pase lento), pero no hay ningún
  ajuste guardado.
- **🩹 ajustado**: hay un ajuste guardado para ese clip.
- **ya estabilizado**: el clip ya tiene una versión estabilizada generada.

**Propagar a otros clips**: dentro del modal, el botón "Propagar a otros clips…" deja
elegir otros vídeos de la **misma carpeta** y copiarles el ajuste actual de golpe —
útil cuando toda una tanda de clips viene de la misma sesión de grabación y necesita
el mismo ajuste, sin tener que repetirlo uno a uno.

El botón masivo **"Estabilizar marcados"** usa automáticamente el ajuste guardado de
cada clip (si lo tiene) en vez de los parámetros del panel de arriba — así no hace
falta reconfigurar nada clip a clip antes de lanzar el lote.

Los clips ya convertidos con un ajuste guardado **también se marcan en el Montaje**
(cuadrícula de clips, insignia "🩹 ajuste de estabilización guardado") y, al
arrastrarlos a la línea de tiempo, el ajuste se aplica automáticamente al clip — sin
tener que volver a Estabilización ni buscar nada en carpetas. (Un clip que ya está
estabilizado no hereda el ajuste al montaje, para no estabilizarlo dos veces — el
ajuste guardado sigue visible en la propia página de Estabilización.)

**Modo rápido (VideoToolbox)**: casilla opcional que usa el motor de vídeo del chip en
vez de codificar por software. Solo acelera de verdad en Apple Silicon con motor de
vídeo dedicado (chips M-series recientes, idealmente M5 o superior) — en otro hardware
puede no estar disponible o no notarse. Con esta casilla, la fase de codificación va
~2 veces más rápida y usa mucha menos CPU, pero la fase de detección del temblor (la que
más tarda) no se acelera, así que el ahorro del proceso completo es modesto (~15%, no
2×). La calidad baja ligeramente (VMAF ≈96/100 frente al modo normal, al mismo tamaño de
archivo). Para la mejor calidad posible, déjala desmarcada.

## Montaje (mini editor)

El módulo **🎬 Montaje** de la barra lateral abre un editor sencillo, estilo Pinnacle
Studio pero muy básico, que trabaja **sobre los clips ya convertidos o estabilizados**
(los `.mp4` de `conversion/` y los `<nombre>_stabilized.mp4`; los `.MTS` originales no
se pueden previsualizar en el navegador).

### 1. Carpeta del proyecto

Igual que en la pantalla principal: escribe la ruta, navega, o usa **Explorar…**. Debe
ser la misma carpeta donde ya convertiste/estabilizaste clips.

### 2. Proyecto

Dale un nombre y pulsa **Guardar** en cualquier momento — el proyecto (clips en la
línea de tiempo, recortes, títulos, duración de transición) se guarda como JSON en
`montaje/proyectos/` dentro de la carpeta del paso 1. Con **Cargar** retomas un
proyecto guardado; con **Nuevo** empiezas de cero sin perder lo guardado.

### 3. Clips disponibles

Cuadrícula con una miniatura por clip (se generan y cachean automáticamente la primera
vez). Haz clic en una miniatura para previsualizar el clip en grande, o arrástrala a la
línea de tiempo de más abajo para añadirlo al montaje.

### 4. Línea de tiempo

- **Arrastra** clips desde la cuadrícula para añadirlos; **arrastra** los propios clips
  de la línea de tiempo entre sí para reordenarlos.
- **Recortar**: abre el mismo reproductor de antes con controles de "Inicio"/"Fin" —
  reproduce el clip y pulsa "Marcar aquí" en el punto exacto, o escribe los segundos a
  mano.
- **Título**: añade un texto (con la fuente del sistema que elijas) y/o una imagen
  superpuesta (un PNG con transparencia funciona como una máscara/logo) durante los
  primeros segundos del clip — tú decides cuántos.
- **✕**: quita el clip de la línea de tiempo (no borra el archivo).
- **Transición entre clips**: duración en segundos (ajustable, pensada para 2-3s) del
  fundido cruzado que se aplica automáticamente entre cada clip consecutivo.
- La duración total estimada del montaje se recalcula sola.
- **Estabilizar**: corrige el temblor de un clip **dentro del propio montaje**, sin
  generar un fichero estabilizado aparte — ver más abajo.

### Estabilizar un clip dentro del montaje

Botón **"Estabilizar"** en cada clip de la línea de tiempo. A diferencia del botón
"Estabilizar" de la pantalla principal (que genera un `.mp4` estabilizado
independiente, `<nombre>_stabilized.mp4`), esto **no genera ningún vídeo todavía** —
solo guarda qué corrección aplicar, y esa corrección se aplica **dentro de la
exportación final**, en el mismo paso que el recorte, el título y las transiciones.
Así un clip nunca pasa por dos recompresiones con pérdida (estabilizar y luego volver
a codificar al exportar el montaje): se analiza una vez y se codifica una vez, al
final.

1. **Analizar clip** — ejecuta el análisis (la parte lenta, sobre todo en 4K) y lo
   cachea junto al propio vídeo (`stabilization_data/`), compartido con el botón de
   estabilizar independiente y con "Analizar y ajustar" en Estabilización: si ya se
   analizó este mismo clip antes con los mismos parámetros, esto es prácticamente
   instantáneo — incluso se carga solo, sin pulsar el botón, si el clip ya estaba
   analizado al abrir este panel.
2. Con el análisis listo aparece una **vista previa en un lienzo** (sobre una copia
   ligera del clip, en `.proxies/`, generada automáticamente) — reproduce, pausa o
   arrastra la barra, y activa o desactiva "con corrección" para comparar.
3. **Automático** o **Personalizado** (sensibilidad al temblor, suavizado, zoom
   automático/dinámico/manual, y un grupo "Avanzado" con más parámetros de vid.stab)
   — al cambiar suavizado, zoom o cualquier parámetro solo de la fase de corrección,
   la vista previa se recalcula y redibuja al instante **en el navegador, sin
   servidor**; solo cambiar la sensibilidad al temblor, la precisión, el paso de
   búsqueda o el contraste mínimo requiere volver a analizar.
   - Importante: el zoom que se ve en esta vista previa es una **aproximación**
     calculada en JavaScript (suavizado con media móvil sobre la trayectoria bruta del
     análisis) — orienta bien para decidir el ajuste, pero no es idéntico al cálculo
     real de `vid.stab`, que usa un algoritmo de optimización más sofisticado. El
     resultado final (al exportar) sí usa el cálculo real.
4. **Guardar** dentro del panel para dejar esa configuración asociada al clip (badge
   "🩹 estabilizado" en la línea de tiempo); **Quitar estabilización** para descartarla.

### 5. Exportar

**Exportar montaje final** renderiza el vídeo completo: recorta cada clip, aplica la
estabilización de los clips que la tengan, superpone los títulos, encadena las
transiciones cruzadas, y guarda el resultado en `montaje/<nombre del proyecto>_final.mp4`
— dentro de la carpeta del proyecto por defecto, o de la carpeta de trabajo configurada
(ver **⚙️ Ajustes**) — todo en una sola pasada de `ffmpeg`. Esto **sí recodifica** el
vídeo entero (es inevitable para poder unir/mezclar clips) — a diferencia del remuxeo,
no es sin pérdida.

## Ajustes

Una única carpeta de trabajo opcional, para toda la app (no es parte de ningún
proyecto). Por defecto, cada carpeta de origen que escaneas es su propia carpeta de
trabajo — lo que generas a partir de ella (`conversion/`, `recompresion/`, `montaje/`,
cachés) se guarda dentro de ella misma, tal como se ha descrito en cada sección de
arriba. Los vídeos estabilizados son la excepción: por defecto se guardan **junto al
original**, no en esta carpeta de trabajo (ver la sección de Estabilización).

Si en **⚙️ Ajustes** fijas una carpeta de trabajo distinta, **toda** carpeta de origen
que escanees a partir de ese momento usa esa misma carpeta para lo que genera — como
una única librería centralizada de todo el material ya tratado, sea cual sea la tarjeta
SD o carpeta de origen de la que provenga cada clip. Esto es especialmente útil para
**Montaje**: la cuadrícula de clips disponibles siempre muestra el mismo histórico
completo, sin depender de qué carpeta de origen tengas puesta en ese momento. En este
caso, la estabilización también usa la carpeta de trabajo — pero replicando la misma
ruta relativa que tendría el vídeo en su carpeta de origen, para no mezclar entre sí
los "junto al original" de vídeos que en realidad vienen de sitios distintos.

Cambiar la carpeta de trabajo no mueve ni borra nada de lo que ya se había generado en
la ubicación anterior — solo afecta a partir de ese momento. Quitarla (botón "Quitar")
vuelve al comportamiento por defecto.

## Notas técnicas

- El renombrado por fecha usa `exiftool` (`DateTimeOriginal`, con varios campos de
  respaldo); si un archivo no tiene metadatos de fecha, se usa la fecha de modificación
  del archivo.
- Al convertir, la fecha de captura también se graba en los metadatos internos del MP4
  (`creation_time`), para que apps como Synology Photos, Plex o Emby ordenen por fecha
  real de grabación y no solo por nombre de archivo.
- El vídeo AVCHD original suele venir entrelazado (1080i), mientras que el `.mp4`/`.mov`
  de cámaras más modernas (incluido el 4K) suele venir progresivo. Estabilizar y montar
  detectan esto automáticamente (`yadif` con `deint=interlaced`) y solo desentrelazan
  cuando hace falta, así que se pueden mezclar clips de ambos orígenes sin problema.
- El montaje encadena los clips con los filtros `xfade`/`acrossfade` de ffmpeg (mismo
  mecanismo que usan editores como Shotcut) y los títulos con `drawtext`/`overlay`;
  todo en una sola pasada de `ffmpeg` con un grafo de filtros construido según la línea
  de tiempo. Cuando un clip tiene estabilización, `vidstabtransform` se inserta en su
  tramo del grafo, sobre el clip *completo* (no el recorte) — `vid.stab` necesita ver
  la misma secuencia de fotogramas que analizó, así que el recorte se aplica después.
- La vista previa de estabilización (tanto en Montaje como en "Analizar y ajustar" de
  Estabilización — es el mismo componente) usa `vidstabtransform` con `debug=1` para
  volcar la trayectoria de cámara detectada, fotograma a fotograma, sin codificar vídeo
  (mucho más rápido que una pasada completa); el navegador la suaviza y dibuja con
  `<canvas>` sobre una copia ligera del clip (`.proxies/`), sin ninguna llamada al
  servidor al mover los sliders de suavizado/zoom.
- El ajuste guardado de un clip (`stabilization_data/<nombre>_ajustes.json`, junto al
  propio vídeo) es solo la elección de parámetros, no un vídeo — es independiente de
  si ese clip llegó a analizarse o estabilizarse de verdad, para poder
  probarlo/guardarlo/descartarlo libremente.

## Pendiente

- Los formatos `.avi`/`.mkv`/`.wmv`/`.3gp` ya se recodifican desde **Recompresión**,
  pero no se han probado todavía con material real — podrían tener códecs que ffmpeg no
  maneje igual de bien que H.264/MP4.
- No hay purga/expiración de las carpetas de caché que genera la app
  (`stabilization_data/`, `.proxies/`, `.miniaturas/`) — crecen sin límite con el uso.
- No hay suite de tests automatizados — todo se verifica manualmente contra clips
  reales durante el desarrollo.
