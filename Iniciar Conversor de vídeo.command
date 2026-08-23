#!/bin/bash
#
# Lanzador para macOS: doble clic desde el Finder.
#
# Al abrir un .command desde el Finder, el PATH que hereda es mínimo
# (/usr/gnu/bin:/usr/local/bin:/bin:/usr/bin) y **no incluye Homebrew**, así que
# ffmpeg y exiftool no se encuentran aunque estén instalados. Por eso lo primero
# que hace es añadir las rutas de Homebrew a mano.

cd "$(dirname "$0")" || exit 1

# Apple Silicon usa /opt/homebrew; los Intel, /usr/local. Y /usr/sbin porque ahí vive
# `diskutil`, que es lo que identifica las tarjetas montadas en /Volumes.
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/sbin:/sbin:$PATH"

VERDE=$'\033[32m'; ROJO=$'\033[31m'; AMARILLO=$'\033[33m'; GRIS=$'\033[90m'; FIN=$'\033[0m'

fallo() {
  echo "${ROJO}$1${FIN}"
  echo
  read -n 1 -s -r -p "Pulsa una tecla para cerrar esta ventana..."
  exit 1
}

echo "${GRIS}Comprobando lo necesario…${FIN}"

command -v python3 >/dev/null || fallo "No se encuentra python3. Instálalo desde python.org o con: brew install python"

FALTAN=""
command -v ffmpeg   >/dev/null || FALTAN="$FALTAN ffmpeg"
command -v exiftool >/dev/null || FALTAN="$FALTAN exiftool"
if [ -n "$FALTAN" ]; then
  fallo "Faltan herramientas del sistema:$FALTAN

Instálalas con:
  brew install ffmpeg exiftool"
fi

# Flask es la única dependencia de Python imprescindible para arrancar.
if ! python3 -c "import flask" 2>/dev/null; then
  fallo "Falta Flask. Instala las dependencias con:
  pip3 install -r requirements.txt"
fi

# Lo siguiente es opcional: la app arranca igual, solo pierde funciones concretas.
AVISOS=""
[ -x "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg" ] || \
  AVISOS="$AVISOS\n  ${AMARILLO}·${FIN} Sin ffmpeg-full: no habrá estabilización ni títulos en el montaje.\n    ${GRIS}brew install ffmpeg-full${FIN}"
python3 -c "import gphoto2" 2>/dev/null || \
  AVISOS="$AVISOS\n  ${AMARILLO}·${FIN} Sin gphoto2: los móviles se detectan pero no se pueden leer sus carpetas.\n    ${GRIS}brew install libgphoto2 && pip3 install gphoto2${FIN}"
python3 -c "import requests" 2>/dev/null || \
  AVISOS="$AVISOS\n  ${AMARILLO}·${FIN} Sin requests: no se podrá enviar al NAS por Synology File Station.\n    ${GRIS}pip3 install -r requirements.txt${FIN}"

echo "${VERDE}Todo listo.${FIN}"
[ -n "$AVISOS" ] && { echo; echo "Funciones no disponibles:"; printf "$AVISOS\n"; }

# Qué hay conectado ahora mismo, para no tener que mirarlo en la app.
echo
TARJETAS=$(ls /Volumes 2>/dev/null | grep -v "^Macintosh HD$")
if [ -n "$TARJETAS" ]; then
  echo "Unidades montadas en /Volumes:"
  echo "$TARJETAS" | sed "s/^/  ${VERDE}·${FIN} /"
else
  echo "${GRIS}No hay tarjetas ni discos externos montados.${FIN}"
fi

MOVIL=$(ioreg -p IOUSB -w0 2>/dev/null | grep -icE "samsung|iphone|ipad|pixel|xiaomi")
[ "$MOVIL" -gt 0 ] 2>/dev/null && echo "  ${VERDE}·${FIN} Hay un móvil conectado por USB"

# Si el puerto ya está ocupado, casi siempre es otra copia de la propia app.
if lsof -nP -iTCP:5050 -sTCP:LISTEN >/dev/null 2>&1; then
  echo
  echo "${AMARILLO}El puerto 5050 ya está en uso.${FIN} Puede que la app ya esté abierta."
  open "http://127.0.0.1:5050"
  echo
  read -n 1 -s -r -p "Pulsa una tecla para cerrar esta ventana..."
  exit 0
fi

echo
echo "Arrancando…"
python3 app.py &
SERVER_PID=$!

# Cerrar la ventana de Terminal no debe dejar el servidor colgado en segundo plano.
detener() {
  echo
  echo "${GRIS}Deteniendo el servidor…${FIN}"
  kill "$SERVER_PID" 2>/dev/null
  wait "$SERVER_PID" 2>/dev/null
  exit 0
}
trap detener INT TERM HUP

# Se espera a que responda de verdad antes de abrir el navegador: con un `sleep` fijo,
# a veces se abría antes de que Flask estuviera escuchando y salía "no se puede conectar".
for _ in $(seq 1 40); do
  curl -s -o /dev/null --max-time 1 "http://127.0.0.1:5050/" && break
  kill -0 "$SERVER_PID" 2>/dev/null || fallo "El servidor se cerró al arrancar. Revisa los mensajes de arriba."
  sleep 0.25
done

open "http://127.0.0.1:5050"

echo
echo "${VERDE}Conversor de vídeo en marcha${FIN} — http://127.0.0.1:5050"
echo "${GRIS}Solo accesible desde este Mac. Pulsa Ctrl+C o cierra la ventana para detenerlo.${FIN}"
echo

wait "$SERVER_PID"
