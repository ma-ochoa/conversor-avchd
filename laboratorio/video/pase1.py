#!/usr/bin/env python
"""Pasada 1: mide TODOS los fotogramas del tramo de ocultacion.

Decodifica el video en gris a 4K por una tuberia (83 fps) y de cada fotograma
saca metricas baratas:
  mx        maximo (detecta caidas a negro del propio video)
  nucleo    pixeles del creciente
  cx,cy     centroide (sesgado hacia el cuerno, pero sirve de semilla)
  borde     pixeles en transicion / pixeles de nucleo -> proxy de nitidez

El proxy de nitidez NO se puede juzgar con un umbral fijo: segun se afina el
creciente crece de forma natural (a 6:30 un fotograma nitido ya da 1.3, y a
6:50 da 2.1). Se compara contra la mediana local, que es lo que separa la
movida real del adelgazamiento progresivo.
"""
import subprocess, sys, json
import numpy as np

V = ("/Users/maochoa/Desktop/tarjetas carmas/eclipse final/"
     "eclipse a6400/PRIVATE/M4ROOT/CLIP/C0001.MP4")
W, H = 3840, 2160
FPS = 25.0
F0, F1 = 750, 10562          # 0:30 -> 7:02.48

p = subprocess.Popen(
    ['ffmpeg', '-v', 'error', '-ss', f'{F0 / FPS:.5f}', '-i', V,
     '-frames:v', str(F1 - F0 + 1), '-pix_fmt', 'gray', '-f', 'rawvideo', '-'],
    stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, bufsize=10 ** 8)

yy, xx = np.mgrid[0:H, 0:W]
res = []
f = F0
while True:
    b = p.stdout.read(W * H)
    if len(b) < W * H:
        break
    a = np.frombuffer(b, dtype=np.uint8).reshape(H, W)
    mx = int(a.max())
    if mx < 32:
        res.append(dict(f=f, mx=mx, nucleo=0, cx=None, cy=None, borde=None))
    else:
        nuc = a >= (0.5 * mx)
        n = int(nuc.sum())
        ys, xs = np.nonzero(nuc)
        bor = int(((a >= 0.2 * mx) & (a < 0.8 * mx)).sum())
        res.append(dict(f=f, mx=mx, nucleo=n,
                        cx=float(xs.mean()), cy=float(ys.mean()),
                        borde=bor / max(n, 1)))
    f += 1
    if (f - F0) % 1000 == 0:
        print(f"  {f - F0}/{F1 - F0 + 1}", flush=True)
p.wait()
json.dump(res, open('pase1.json', 'w'))
print(f"medidos {len(res)} fotogramas")

mx = np.array([r['mx'] for r in res])
neg = int((mx < 32).sum())
print(f"  caidas a negro / sin senal: {neg}")
bo = np.array([r['borde'] if r['borde'] is not None else np.nan for r in res])
print(f"  proxy de borde: p50={np.nanpercentile(bo,50):.2f} "
      f"p90={np.nanpercentile(bo,90):.2f} p99={np.nanpercentile(bo,99):.2f}")
