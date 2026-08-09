# Conversor AVCHD

Interfaz web (Flask, en local) para convertir los clips de vídeo de una cámara/camcorder
(AVCHD `.MTS`/`.M2TS`, y también `.mp4`/`.mov` — incluido 4K) a MP4 **sin recompresión de
vídeo** (solo se cambia el contenedor), renombrar vídeos y fotos con su fecha y hora real
de captura, estabilizar clips con temblor de cámara, y montar un vídeo final (recortes,
títulos y transiciones) con un mini editor integrado. Pensado para que el resultado se
reproduzca sin problemas al subirlo a un NAS (Synology Photos, Plex, Emby, etc.) y se vea
bien tanto en el móvil como en la TV.

## Funciones

- **Remuxeo sin pérdida**: copia el vídeo H.264 bit a bit, solo cambia el contenedor a
  `.mp4` — vale tanto para AVCHD (`.MTS`/`.M2TS`) como para cámaras que ya graban en
  `.mp4`/`.mov` (incluido 4K), cuyo audio (a menudo PCM sin comprimir) puede necesitar el
  mismo recodificado opcional a AAC que el AC-3 de AVCHD. No hay recompresión ni pérdida
  de calidad de vídeo en ningún caso.
- **Renombrado por fecha de captura**: tanto vídeos como fotos se renombran a
  `AAAAMMDD_HHMMSS.ext` usando la fecha real leída de los metadatos (con `exiftool`),
  no la fecha de copia del archivo.
- **Estabilización opcional** (independiente del remuxeo): corrige el temblor de cámara
  con `vid.stab` (dos pasadas: detección + corrección). Esto sí recodifica el vídeo —
  es inevitable para poder corregirlo — y recorta ligeramente los bordes.
- **Montaje**: mini editor (submenú "🎬 Montaje") para unir clips ya convertidos,
  recortarlos, añadir títulos (texto o imagen con transparencia) y transiciones
  cruzadas, guardando el trabajo como proyecto para continuarlo más tarde.
- **Explorador de carpetas nativo**: botón "Explorar…" que abre el selector de carpetas
  de macOS (Finder), además de un navegador de carpetas dentro de la propia página.
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

## Arranque

**Opción rápida (macOS)**: haz doble clic en `Iniciar Conversor AVCHD.command` — arranca
el servidor y abre el navegador automáticamente.

**Desde terminal**:

```bash
python3 app.py
```

Y abre http://127.0.0.1:5050 (el servidor solo escucha en local, no es accesible desde
otros equipos de la red).

## Uso

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
- **Otros formatos** (`.avi`, `.mkv`, `.wmv`, `.3gp`) — se listan pero de momento no se
  procesan (ver [Pendiente](#pendiente-fase-2)).

### 3. Convertir

Marca los clips/fotos que quieras y pulsa **Convertir seleccionados**. El resultado se
guarda en una carpeta `conversion/` dentro de la carpeta de origen, lista para subir al
NAS. Si el audio del vídeo no se oye en el navegador o el móvil (AC-3 en AVCHD, o PCM sin
comprimir en muchas cámaras que graban directamente en `.mp4`/`.mov`), marca
**"Recodificar audio a AAC si no es compatible"** — solo afecta al audio, el vídeo se
sigue copiando sin recomprimir en cualquier caso.

Las conversiones ya hechas se recuerdan (`conversion/.manifest.json`): puedes reescanear
la misma carpeta tras grabar más clips sin reconvertir lo ya hecho, salvo que actives
**"Forzar reconversión"**.

### 4. Estabilizar (opcional)

En la tabla de vídeos hay una columna **"Estabilizar"** aparte de la de convertir —
marca ahí los clips con temblor de cámara y pulsa **Estabilizar marcados**. El resultado
se guarda en una carpeta `estabilizado/` (independiente de `conversion/`), y muestra
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

También se recuerda lo ya estabilizado (`estabilizado/.manifest.json`), con la misma
opción de forzar.

**Modo rápido (VideoToolbox)**: casilla opcional que usa el motor de vídeo del chip en
vez de codificar por software. Solo acelera de verdad en Apple Silicon con motor de
vídeo dedicado (chips M-series recientes, idealmente M5 o superior) — en otro hardware
puede no estar disponible o no notarse. Con esta casilla, la fase de codificación va
~2 veces más rápida y usa mucha menos CPU, pero la fase de detección del temblor (la que
más tarda) no se acelera, así que el ahorro del proceso completo es modesto (~15%, no
2×). La calidad baja ligeramente (VMAF ≈96/100 frente al modo normal, al mismo tamaño de
archivo). Para la mejor calidad posible, déjala desmarcada.

## Montaje (mini editor)

Desde el enlace **🎬 Montaje** (arriba a la derecha) se abre un editor sencillo, estilo
Pinnacle Studio pero muy básico, que trabaja **sobre los clips ya convertidos o
estabilizados** (los `.mp4` de `conversion/`/`estabilizado/`; los `.MTS` originales no
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

### 5. Exportar

**Exportar montaje final** renderiza el vídeo completo: recorta cada clip, superpone
los títulos, encadena las transiciones cruzadas, y guarda el resultado en
`montaje/<nombre del proyecto>_final.mp4` dentro de la carpeta del proyecto. Esto
**sí recodifica** el vídeo entero (es inevitable para poder unir/mezclar clips) — a
diferencia del remuxeo, no es sin pérdida.

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
  de tiempo.

## Pendiente (fase 2)

Se convierten y estabilizan vídeos AVCHD (`.MTS`/`.M2TS`) y de la familia MP4/MOV
(`.mp4`, `.mov`, `.m4v`, incluido 4K). La pantalla ya lista, bajo "Otros formatos",
cualquier vídeo en un contenedor distinto (`.avi`, `.mkv`, `.wmv`, `.3gp`) que encuentre
en la carpeta, para una futura fase en la que también se recompriman/normalicen esos
formatos — no se han probado todavía y podrían tener códecs que ffmpeg no maneje igual
de bien.
