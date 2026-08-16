#!/usr/bin/env python
"""Estabiliza el video de la puesta de sol (a66, grabado a pulso).

Aqui el Sol NO sirve de referencia: se pone y desaparece a los 48 s. La
referencia es el paisaje (horizonte y ramas), medido por correlacion de fase.

No se bloquea el encuadre del todo: el recorrido de la camara es de 514x456 px
sobre 1920x1080 y bloquearlo dejaria un cuadro inservible. Se quita el temblor
(alta frecuencia) y se respeta la deriva lenta, que ademas es intencionada
porque vas siguiendo al Sol mientras baja.

El desplazamiento se aplica moviendo el ORIGEN DEL RECORTE, no remuestreando:
cada pixel de salida es un pixel original, sin interpolar.
"""
import subprocess, json, os, sys
import numpy as np

ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
M = f"{ROOT}/eclipse a66/PRIVATE/AVCHD/BDMV/STREAM/00000.MTS"
DST = f"{ROOT}/secuencias/a66/puesta_estabilizada.mov"
W, H = 1920, 1080
VENT = 25                 # ventana de suavizado: 1 s
CW, CH = 1648, 927        # recorte 16:9 que absorbe el temblor residual


def suave(s, w):
    k = np.ones(w) / w
    return np.convolve(np.pad(s, (w // 2, w // 2), mode='edge'), k, mode='valid')[:len(s)]


cam = json.load(open('puesta_cam.json'))
n = len(cam) + 1
px = np.zeros(n); py = np.zeros(n)
for i, c in enumerate(cam, 1):
    px[i] = c['dx'] * 2.0        # medido a 960x540
    py[i] = c['dy'] * 2.0
rx = px - suave(px, VENT)        # lo que hay que corregir: solo el temblor
ry = py - suave(py, VENT)

bx, by = (W - CW) // 2, (H - CH) // 2
mx, my = bx, by                  # margen disponible a cada lado
ox = np.clip(np.rint(rx), -mx, mx).astype(int)
oy = np.clip(np.rint(ry), -my, my).astype(int)
recortados = int(((np.abs(np.rint(rx)) > mx) | (np.abs(np.rint(ry)) > my)).sum())

dec = subprocess.Popen(
    ['ffmpeg', '-v', 'error', '-i', M, '-vf', 'bwdif=mode=0',
     '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
    stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, bufsize=10 ** 8)
enc = subprocess.Popen(
    ['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
     '-s', f'{CW}x{CH}', '-r', '25', '-i', '-',
     '-vf', f'scale={W}:{H}:flags=lanczos',
     '-c:v', 'prores_ks', '-profile:v', '3', '-pix_fmt', 'yuv422p10le',
     '-y', DST], stdin=subprocess.PIPE)

i = 0
while True:
    b = dec.stdout.read(W * H * 3)
    if len(b) < W * H * 3:
        break
    a = np.frombuffer(b, dtype=np.uint8).reshape(H, W, 3)
    x0 = bx + (ox[i] if i < len(ox) else 0)
    y0 = by + (oy[i] if i < len(oy) else 0)
    enc.stdin.write(np.ascontiguousarray(a[y0:y0 + CH, x0:x0 + CW]).tobytes())
    i += 1
    if i % 300 == 0:
        print(f"  {i}/{n}", flush=True)
enc.stdin.close(); enc.wait(); dec.wait()

print(f"\nfotogramas: {i}  ({i/25:.1f} s)")
print(f"correccion aplicada: p95 = {np.percentile(np.abs(rx),95):.0f} x "
      f"{np.percentile(np.abs(ry),95):.0f} px   max = {np.abs(rx).max():.0f} x "
      f"{np.abs(ry).max():.0f} px")
print(f"recorte {CW}x{CH} reescalado a {W}x{H} ({W/CW:.2f}x)")
print(f"fotogramas con temblor mayor que el margen (correccion limitada): {recortados}")
