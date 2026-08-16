# Conversor de vídeo

Aplicación web (Flask, en local) para el flujo de trabajo completo de vídeo de cámara —
AVCHD `.MTS`/`.M2TS` y `.mp4`/`.mov` (incluido 4K) — organizada como un editor con
**cuatro módulos** en una barra lateral persistente, cada uno con su propia carpeta de
proyecto (se recuerda al cambiar de sección):

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

## Arranque

**Opción rápida (macOS)**: haz doble clic en `Iniciar Conversor AVCHD.command` — arranca
el servidor y abre el navegador automáticamente.

**Desde terminal**:

```bash
python3 app.py
```

Y abre http://127.0.0.1:5050 (el servidor solo escucha en local, no es accesible desde
otros equipos de la red).

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

Marca los clips/fotos que quieras y pulsa **Convertir seleccionados**. El resultado se
guarda en una carpeta `conversion/` dentro de la carpeta de origen, lista para subir al
NAS. Si el audio del vídeo no se oye en el navegador o el móvil (AC-3 en AVCHD, o PCM sin
comprimir en muchas cámaras que graban directamente en `.mp4`/`.mov`), marca
**"Recodificar audio a AAC si no es compatible"** — solo afecta al audio, el vídeo se
sigue copiando sin recomprimir en cualquier caso.

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
elegido). El resultado se guarda en `recompresion/` dentro de la carpeta de origen, con
el mismo renombrado por fecha que el resto de la app, y muestra cuánto se ha reducido
el tamaño (p. ej. "72.4 MB → 3.8 MB (-94.8%)").

## Estabilización

En la tabla de vídeos hay una columna **"Estabilizar"** — marca los clips con temblor
de cámara y pulsa **Estabilizar marcados**. El resultado se guarda en una carpeta
`estabilizado/` (independiente de `conversion/`), y muestra estadísticas de cuánto ha
tenido que corregir:

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

**Automático vs. personalizado**: por defecto la app usa unos parámetros estándar
(equivalente a "automático" en Pinnacle — recorte mínimo para tapar los bordes). Si
marcas **"Personalizado"** puedes ajustar:

- **Sensibilidad al temblor**: cuánto asume el análisis que tiembla la cámara.
- **Suavizado**: cuántos fotogramas se usan para suavizar el movimiento — más alto da un
  resultado más "flotante", pero necesita más recorte.
- **Zoom/recorte**: automático (fijo para todo el vídeo), automático dinámico (varía
  según haga falta en cada momento) o **manual** — tú eliges el porcentaje exacto de
  zoom, igual que el control de Pinnacle.

El análisis (la parte lenta) se cachea por clip (`.vidstab_cache/`): si solo cambias el
suavizado o el zoom y vuelves a procesar el mismo clip, no hace falta repetirlo — solo
la fase de corrección, mucho más rápida. Cambiar la sensibilidad al temblor sí invalida
la caché y repite el análisis.

### Analizar y ajustar un clip antes de recomprimir

Cada fila de la tabla tiene un botón **"🔍 Analizar y ajustar"** que abre una
previsualización del clip en el navegador — mueves los sliders de suavizado/zoom y ves
al instante una aproximación del resultado, **sin generar ningún vídeo nuevo**. Cuando
el ajuste te convence, **"Guardar ajuste"** lo deja guardado para ese clip (puedes
volver más tarde, probar otra cosa, y guardar o **"Descartar ajuste guardado"** sin que
eso afecte a si el clip está o no ya estabilizado en disco).

La columna "Estado" refleja esto por clip:

- **—**: sin analizar.
- **🔍 analizado**: ya se ha calculado el análisis (pase lento), pero no hay ningún
  ajuste guardado.
- **🩹 ajustado**: hay un ajuste guardado para ese clip.
- **ya estabilizado**: el clip ya tiene una versión estabilizada generada.

El botón masivo **"Estabilizar marcados"** usa automáticamente el ajuste guardado de
cada clip (si lo tiene) en vez de los parámetros del panel de arriba — así no hace
falta reconfigurar nada clip a clip antes de lanzar el lote.

Los clips ya convertidos con un ajuste guardado **también se marcan en el Montaje**
(cuadrícula de clips, insignia "🩹 ajuste de estabilización guardado") y, al
arrastrarlos a la línea de tiempo, el ajuste se aplica automáticamente al clip — sin
tener que volver a Estabilización ni buscar nada en carpetas. (Un clip que ya viene de
una carpeta `estabilizado/` no hereda el ajuste al montaje, para no estabilizarlo dos
veces — el ajuste guardado sigue visible en la propia página de Estabilización.)

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
(los `.mp4` de `conversion/`/`estabilizado/`; los `.MTS` originales no se pueden
previsualizar en el navegador).

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
"Estabilizar" de la pantalla principal (que genera un `.mp4` estabilizado independiente
en `estabilizado/`), esto **no genera ningún vídeo todavía** — solo guarda qué
corrección aplicar, y esa corrección se aplica **dentro de la exportación final**, en el
mismo paso que el recorte, el título y las transiciones. Así un clip nunca pasa por dos
recompresiones con pérdida (estabilizar y luego volver a codificar al exportar el
montaje): se analiza una vez y se codifica una vez, al final.

1. **Analizar clip** — ejecuta el análisis (la parte lenta, sobre todo en 4K) y lo
   cachea en `.vidstab_cache/`, compartido con el botón de estabilizar independiente:
   si ya estabilizaste este mismo clip antes con los mismos parámetros, esto es
   prácticamente instantáneo.
2. Con el análisis listo aparece una **vista previa en un lienzo** (sobre una copia
   ligera del clip, en `.proxies/`, generada automáticamente) — reproduce, pausa o
   arrastra la barra, y activa o desactiva "con corrección" para comparar.
3. **Automático** o **Personalizado** (sensibilidad al temblor, suavizado, zoom
   automático/dinámico/manual) — al cambiar suavizado o zoom, la vista previa se
   recalcula y redibuja al instante **en el navegador, sin servidor**; solo cambiar la
   sensibilidad al temblor requiere volver a analizar.
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
dentro de la carpeta del proyecto — todo en una sola pasada de `ffmpeg`. Esto
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
  de tiempo. Cuando un clip tiene estabilización, `vidstabtransform` se inserta en su
  tramo del grafo, sobre el clip *completo* (no el recorte) — `vid.stab` necesita ver
  la misma secuencia de fotogramas que analizó, así que el recorte se aplica después.
- La vista previa de estabilización (tanto en Montaje como en "Analizar y ajustar" de
  Estabilización — es el mismo componente) usa `vidstabtransform` con `debug=1` para
  volcar la trayectoria de cámara detectada, fotograma a fotograma, sin codificar vídeo
  (mucho más rápido que una pasada completa); el navegador la suaviza y dibuja con
  `<canvas>` sobre una copia ligera del clip (`.proxies/`), sin ninguna llamada al
  servidor al mover los sliders de suavizado/zoom.
- El ajuste guardado de un clip (`.vidstab_cache/.manifest.json`) es solo la elección
  de parámetros, no un vídeo — es independiente de si ese clip llegó a analizarse o
  estabilizarse de verdad, para poder probarlo/guardarlo/descartarlo libremente.

## Pendiente

- Los formatos `.avi`/`.mkv`/`.wmv`/`.3gp` ya se recodifican desde **Recompresión**,
  pero no se han probado todavía con material real — podrían tener códecs que ffmpeg no
  maneje igual de bien que H.264/MP4.
- No hay purga/expiración de las carpetas de caché que genera la app
  (`.vidstab_cache/`, `.proxies/`, `.miniaturas/`) — crecen sin límite con el uso.
- No hay suite de tests automatizados — todo se verifica manualmente contra clips
  reales durante el desarrollo.
