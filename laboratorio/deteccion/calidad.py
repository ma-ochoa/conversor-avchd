#!/usr/bin/env python
"""Mide nitidez y sobreexposicion de cada recorte.

Nitidez: el limbo esta siempre a la misma distancia del centro, asi que se
mide la ANCHURA DE TRANSICION del borde (distancia radial entre el 20 % y el
80 % del escalon). Un limbo nitido cambia en 2-4 px; uno movido, en 20 o mas.
Es independiente de la exposicion, que es justo lo que hace falta aqui.

Sobreexposicion: fraccion del cuadro pegada a 255.
"""
import glob, json, os
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
OUT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final/recortadas"
R_CAM = {'a6400_240mm': 281.6, 'a66_300mm': 352.0, 'a66_puesta_de_sol': 352.0}
NRAY = 360

res = []
for p in sorted(glob.glob(os.path.join(OUT, '**', '*.png'), recursive=True)):
    rel = os.path.relpath(p, OUT)
    cam = next((k for k in R_CAM if k in rel), None)
    if cam is None:
        continue
    R = R_CAM[cam]
    a = np.asarray(Image.open(p).convert('L'), dtype=np.float32)
    n = a.shape[0]
    c = n / 2.0

    ang = np.linspace(0, 2 * np.pi, NRAY, endpoint=False)
    rs = np.arange(R * 0.80, R * 1.20, 0.5)
    X = np.clip(np.rint(c + np.outer(rs, np.cos(ang))).astype(int), 0, n - 1)
    Y = np.clip(np.rint(c + np.outer(rs, np.sin(ang))).astype(int), 0, n - 1)
    prof = a[Y, X]                                  # (radios, rayos)

    anchos = []
    for j in range(NRAY):
        v = prof[:, j]
        lo, hi = float(v.min()), float(v.max())
        if hi - lo < 25:                            # sin escalon claro en ese rayo
            continue
        t20, t80 = lo + 0.2 * (hi - lo), lo + 0.8 * (hi - lo)
        i20 = np.nonzero(v >= t20)[0]
        i80 = np.nonzero(v >= t80)[0]
        if not len(i20) or not len(i80):
            continue
        # borde descendente (fotosfera dentro) o ascendente (corona fuera)
        w = abs(rs[i80[0]] - rs[i20[0]]) if i80[0] >= i20[0] else \
            abs(rs[i20[-1]] - rs[i80[-1]])
        if 0 < w < R * 0.35:
            anchos.append(w)

    res.append(dict(
        file=os.path.basename(p), rel=rel, cam=cam,
        ancho_limbo=float(np.median(anchos)) if len(anchos) >= 20 else None,
        n_rayos=len(anchos),
        quemado_cuadro=float((a >= 253).mean()),
        p999=float(np.percentile(a, 99.9)),
    ))
json.dump(res, open('calidad.json', 'w'), indent=1)
print(len(res))
