#!/bin/bash
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null || ! command -v exiftool >/dev/null; then
  echo "Faltan herramientas necesarias. Instálalas con:"
  echo "  brew install ffmpeg ffmpeg-full exiftool"
  read -n 1 -s -r -p "Pulsa una tecla para cerrar..."
  exit 1
fi

python3 app.py &
SERVER_PID=$!

sleep 1.5
open "http://127.0.0.1:5050"

echo "Conversor AVCHD en marcha (http://127.0.0.1:5050)."
echo "Cierra esta ventana o pulsa Ctrl+C para detener el servidor."
wait "$SERVER_PID"
