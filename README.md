# Conversor AVCHD

Interfaz web (Flask, en local) para convertir los clips AVCHD (`.MTS`/`.M2TS`) de una
cámara/camcorder a MP4 **sin recompresión de vídeo** (solo se cambia el contenedor),
renombrar vídeos y fotos con su fecha y hora real de captura, y opcionalmente
**estabilizar** los clips con temblor de cámara. Pensado para que el resultado se
reproduzca sin problemas al subirlo a un NAS (Synology Photos, Plex, Emby, etc.) y se
vea bien tanto en el móvil como en la TV.

## Funciones

- **Remuxeo sin pérdida**: copia el vídeo H.264 bit a bit, solo cambia el contenedor
  de `.MTS` a `.mp4`. No hay recompresión ni pérdida de calidad.
- **Renombrado por fecha de captura**: tanto vídeos como fotos se renombran a
  `AAAAMMDD_HHMMSS.ext` usando la fecha real leída de los metadatos (con `exiftool`),
  no la fecha de copia del archivo.
- **Estabilización opcional** (independiente del remuxeo): corrige el temblor de cámara
  con `vid.stab` (dos pasadas: detección + corrección). Esto sí recodifica el vídeo —
  es inevitable para poder corregirlo — y recorta ligeramente los bordes.
- **Explorador de carpetas nativo**: botón "Explorar…" que abre el selector de carpetas
  de macOS (Finder), además de un navegador de carpetas dentro de la propia página.
- No se modifican ni se borran los archivos originales en ningún momento.

## Requisitos

- macOS (usa AppleScript para el selector de carpetas nativo y, opcionalmente,
  VideoToolbox para la estabilización acelerada por hardware).
- Python 3.10+
- [ffmpeg-full](https://ffmpeg.org/) (necesario para la estabilización, incluye
  `libvidstab`) y [exiftool](https://exiftool.org/):

  ```bash
  brew install ffmpeg ffmpeg-full exiftool
  ```

  `ffmpeg-full` se instala aparte de `ffmpeg` sin pisarlo (queda "keg-only"); la app lo
  busca automáticamente en `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` cuando lo necesita.
  Si solo vas a usar el remuxeo (sin estabilización), basta con `ffmpeg` normal.

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
subcarpeta) la estructura `AVCHD/BDMV/STREAM` de la cámara — por ejemplo, la tarjeta SD
montada, o una copia de la carpeta `PRIVATE` de la cámara.

### 2. Escanear

Pulsa **Escanear esta carpeta**. La app busca de forma recursiva:

- **Vídeos AVCHD** (`.MTS`/`.M2TS`) — con su fecha de captura y el nombre que tendrán al
  convertir.
- **Fotos** (`.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`, `.tif`, `.tiff`) — mismo criterio
  de fecha/renombrado, sin conversión (se copian tal cual).
- **Otros vídeos** no AVCHD (`.mp4`, `.mov`, etc.) — se listan pero de momento no se
  procesan (ver [Pendiente](#pendiente-fase-2)).

### 3. Convertir

Marca los clips/fotos que quieras y pulsa **Convertir seleccionados**. El resultado se
guarda en una carpeta `conversion/` dentro de la carpeta de origen, lista para subir al
NAS. Si el audio del vídeo es AC-3 y no se oye en el navegador o el móvil, marca
**"Recodificar audio AC-3 a AAC"** — solo afecta al audio, el vídeo se sigue copiando
sin recomprimir.

Las conversiones ya hechas se recuerdan (`conversion/.manifest.json`): puedes reescanear
la misma carpeta tras grabar más clips sin reconvertir lo ya hecho, salvo que actives
**"Forzar reconversión"**.

### 4. Estabilizar (opcional)

En la tabla de vídeos AVCHD hay una columna **"Estabilizar"** aparte de la de convertir —
marca ahí los clips con temblor de cámara y pulsa **Estabilizar marcados**. El resultado
se guarda en una carpeta `estabilizado/` (independiente de `conversion/`), y muestra
estadísticas de cuánto ha tenido que corregir:

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

## Notas técnicas

- El renombrado por fecha usa `exiftool` (`DateTimeOriginal`, con varios campos de
  respaldo); si un archivo no tiene metadatos de fecha, se usa la fecha de modificación
  del archivo.
- Al convertir, la fecha de captura también se graba en los metadatos internos del MP4
  (`creation_time`), para que apps como Synology Photos, Plex o Emby ordenen por fecha
  real de grabación y no solo por nombre de archivo.
- El vídeo AVCHD original suele venir entrelazado (1080i); antes de estabilizar se
  desentrelaza (`yadif`).

## Pendiente (fase 2)

De momento solo se convierten y estabilizan clips AVCHD. La pantalla ya lista, bajo
"Otros vídeos", cualquier vídeo en otro formato (MP4, MOV, etc.) que encuentre en la
carpeta, para una futura fase en la que también se recompriman/normalicen esos formatos.
