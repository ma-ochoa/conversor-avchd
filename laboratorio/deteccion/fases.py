#!/usr/bin/env python
"""Clasifica cada recorte en parcial / totalidad y mide su brillo aparente.

Totalidad = no hay fotosfera. Se compara el brillo del anillo justo POR DENTRO
del limbo (0.75-0.98 R, donde vive el creciente en cualquier fase parcial, por
fino que sea) con el de justo POR FUERA (1.05-1.40 R, corona o cielo).
  parcial   -> dentro mucho mas brillante que fuera
  totalidad -> dentro oscuro (disco lunar) y fuera brillante (corona)
"""
import glob, json, os
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
OUT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final/recortadas"
R_CAM = {'a6400_240mm': 281.6, 'a66_300mm': 352.0, 'a66_puesta_de_sol': 352.0}

res = []
for p in sorted(glob.glob(os.path.join(OUT, '**', '*.png'), recursive=True)):
    rel = os.path.relpath(p, OUT)
    cam = next((k for k in R_CAM if k in rel), None)
    if cam is None:
        continue
    R = R_CAM[cam]
    im = Image.open(p).convert('L')
    d = 4
    im = im.resize((im.size[0] // d, im.size[1] // d), Image.BOX)
    a = np.asarray(im, dtype=np.float32)
    n = a.shape[0]
    c = n / 2.0
    yy, xx = np.mgrid[0:n, 0:n]
    rr = np.hypot(xx - c, yy - c) / (R / d)

    dentro = a[(rr >= 0.75) & (rr <= 0.98)]
    fuera = a[(rr >= 1.05) & (rr <= 1.40)]
    mi = float(np.percentile(dentro, 99)) if dentro.size else 0.0
    mo = float(np.percentile(fuera, 99)) if fuera.size else 0.0
    res.append(dict(
        file=os.path.basename(p), rel=rel, cam=cam,
        dentro=mi, fuera=mo, ratio=mi / max(mo, 1.0),
        media=float(a[rr <= 1.5].mean()),            # brillo del SUJETO (Sol+corona)
        media_cuadro=float(a.mean()),
        p90=float(np.percentile(a, 90)),
    ))
json.dump(res, open('fases.json', 'w'), indent=1)
print(len(res))
