#!/usr/bin/env python
"""Mide el nivel de exposicion resultante de cada recorte.

El Sol esta siempre en el centro, asi que se mide dentro de un disco fijo
alrededor del centro: eso da 'cuanta luz recogio' la toma, con independencia
de la velocidad/ISO/apertura que usara la camara y de la fase del eclipse.
"""
import glob, json, os, math
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
OUT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final/recortadas"
CARP = [('a6400_240mm', 281.6, 2000), ('borde_relleno_negro/a6400_240mm', 281.6, 2000),
        ('a66_300mm', 352.0, 2500), ('borde_relleno_negro/a66_300mm', 352.0, 2500),
        ('a66_puesta_de_sol', 352.0, 2500), ('revisar_fotograma_negro', 281.6, 2000)]

res = []
for sub, R, lado in CARP:
    for p in sorted(glob.glob(os.path.join(OUT, sub, '*.png'))):
        im = Image.open(p).convert('L')
        d = 4
        im = im.resize((im.size[0] // d, im.size[1] // d), Image.BOX)
        a = np.asarray(im, dtype=np.float32)
        n = a.shape[0]
        yy, xx = np.mgrid[0:n, 0:n]
        c = n / 2.0
        rr = np.hypot(xx - c, yy - c)
        rs = R / d
        disco = a[rr <= rs * 1.35]          # Sol + corona interior
        cielo = a[(rr > rs * 2.2) & (rr < rs * 3.2)]   # fondo de cielo
        res.append(dict(
            file=os.path.basename(p), carpeta=sub,
            p50=float(np.percentile(disco, 50)),
            p90=float(np.percentile(disco, 90)),
            p99=float(np.percentile(disco, 99)),
            cielo=float(np.percentile(cielo, 50)) if cielo.size else 0.0,
            quemado=float((disco >= 252).mean()),
        ))
json.dump(res, open('brillo.json', 'w'), indent=1)
print(len(res))
