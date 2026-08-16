#!/usr/bin/env python
"""Mide el temblor del video de la puesta (a pulso) por correlacion de fase.

El Sol se pone y desaparece, asi que NO sirve de referencia: se estabiliza
contra el paisaje (horizonte y ramas), que es lo que debe quedarse quieto.
La correlacion de fase blanquea el espectro, o sea que se apoya en los bordes
fuertes -> justo las ramas y la linea del horizonte.
"""
import subprocess, sys, json
import numpy as np

M = ("/Users/maochoa/Desktop/tarjetas carmas/eclipse final/"
     "eclipse a66/PRIVATE/AVCHD/BDMV/STREAM/00000.MTS")
W, H = 960, 540           # analisis a media resolucion
FPS = 25.0

p = subprocess.Popen(
    ['ffmpeg', '-v', 'error', '-i', M, '-vf', f'bwdif=mode=0,scale={W}:{H}',
     '-pix_fmt', 'gray', '-f', 'rawvideo', '-'],
    stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, bufsize=10 ** 8)

win = np.outer(np.hanning(H), np.hanning(W))
prev = None
dx = dy = 0.0
cam = []
n = 0
while True:
    b = p.stdout.read(W * H)
    if len(b) < W * H:
        break
    a = np.frombuffer(b, dtype=np.uint8).reshape(H, W).astype(np.float32)
    a = a - a.mean()
    F = np.fft.rfft2(a * win)
    if prev is not None:
        C = F * np.conj(prev)
        C /= np.maximum(np.abs(C), 1e-9)
        c = np.fft.irfft2(C, s=(H, W))
        j = int(np.argmax(c))
        py, px = divmod(j, W)
        if py > H // 2: py -= H
        if px > W // 2: px -= W
        pico = float(c.max() / (np.abs(c).mean() + 1e-9))
        dx += px
        dy += py
        cam.append(dict(n=n, dx=dx, dy=dy, ddx=px, ddy=py, pico=pico))
    prev = F
    n += 1
p.wait()
json.dump(cam, open('puesta_cam.json', 'w'))

x = np.array([c['dx'] for c in cam]) * 2      # a pixeles de 1920x1080
y = np.array([c['dy'] for c in cam]) * 2
v = np.hypot([c['ddx'] for c in cam], [c['ddy'] for c in cam]) * 2
print(f"fotogramas: {n}  ({n/FPS:.1f} s)")
print(f"recorrido acumulado de la camara:")
print(f"   x: {x.min():+7.0f} .. {x.max():+7.0f}  (rango {x.max()-x.min():.0f} px)")
print(f"   y: {y.min():+7.0f} .. {y.max():+7.0f}  (rango {y.max()-y.min():.0f} px)")
print(f"velocidad entre fotogramas: mediana {np.median(v):.1f} px  "
      f"p95 {np.percentile(v,95):.1f}  max {v.max():.0f}")
print(f"fotogramas con salto >25 px (rolling shutter probable): {(v>25).sum()}")
