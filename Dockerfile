# El ffmpeg de Debian/Ubuntu ya trae libvidstab + libfreetype + libx264 de serie
# (comprobado con "ffmpeg -filters | grep vidstab" en esta misma imagen base) — a
# diferencia de macOS, donde hace falta el paquete aparte "ffmpeg-full" de Homebrew.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libimage-exiftool-perl \
    fonts-dejavu-core \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY converter/ converter/
COPY static/ static/
COPY templates/ templates/

EXPOSE 5050

CMD ["python", "app.py"]
