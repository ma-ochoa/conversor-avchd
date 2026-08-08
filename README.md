# Conversor AVCHD

Interfaz web (Flask) para convertir los clips AVCHD (`.MTS`/`.M2TS`) de la cámara Sony a
MP4 **sin recompresión de vídeo** (solo se cambia el contenedor), y renombrar vídeos y
fotos con su fecha y hora real de captura. Pensado para que el resultado se reproduzca
sin problemas al subirlo al NAS (Synology Photos, Plex, Emby, etc.).

## Requisitos

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) y [exiftool](https://exiftool.org/) en el `PATH`:

  ```bash
  brew install ffmpeg exiftool
  ```

## Instalación y arranque

```bash
pip3 install -r requirements.txt
python3 app.py
```

Abre http://127.0.0.1:5050 en el navegador (solo accesible desde este ordenador).

## Uso

1. Navega hasta la carpeta que contiene la estructura `AVCHD/BDMV/STREAM` (por ejemplo,
   la tarjeta SD montada, o una copia de la carpeta `PRIVATE` de la cámara) y pulsa
   **Escanear esta carpeta**.
2. Revisa los clips detectados, su fecha de captura (leída de los metadatos con
   `exiftool`) y el nombre de destino (`AAAAMMDD_HHMMSS.mp4`).
3. Marca/desmarca lo que quieras convertir y pulsa **Convertir seleccionados**.
4. Los archivos resultantes se guardan en una carpeta `conversion` dentro de la carpeta
   de origen, lista para subir al NAS. Los originales no se tocan ni se borran.

Las conversiones ya hechas se recuerdan (fichero `conversion/.manifest.json`), así que
puedes volver a escanear la misma carpeta tras grabar más clips sin reconvertir lo ya
hecho — salvo que actives "Forzar reconversión".

### Sobre el audio

El vídeo (H.264) siempre se copia bit a bit, sin pérdida. El audio de las cámaras Sony
en AVCHD suele ser AC-3, que algunos navegadores (Chrome/Android) no decodifican. Si
notas que un vídeo se ve pero no se oye en el móvil o el navegador, marca
"Recodificar audio AC-3 a AAC" — solo afecta al audio, el vídeo sigue copiándose sin
recomprimir.

## Fase 2 (pendiente)

De momento solo se convierten clips AVCHD. La pantalla ya lista, bajo "Otros vídeos",
cualquier vídeo en otro formato (MP4, MOV, etc.) que encuentre en la carpeta, para una
futura fase en la que también se recompriman/normalicen esos formatos.
