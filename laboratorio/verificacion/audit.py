#!/usr/bin/env python
"""Vuelve a detectar el Sol en los PNG recortados y mide el descentrado."""
import glob, os, sys
import numpy as np
import detect

OUT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final/recortadas"
CARP = [('a6400_240mm', 240.0), ('borde_relleno_negro/a6400_240mm', 240.0),
        ('a66_300mm', 300.0), ('borde_relleno_negro/a66_300mm', 300.0),
        ('a66_puesta_de_sol', 300.0)]

peor = []
for sub, foc in CARP:
    ds = []
    for p in sorted(glob.glob(os.path.join(OUT, sub, '*.png'))):
        r = detect.detect(p, foc, div=2)
        im_w = r['W']
        d = float(np.hypot(r['cx'] - im_w / 2, r['cy'] - im_w / 2))
        ds.append(d)
        peor.append((d, sub, os.path.basename(p), r['method']))
    ds = np.array(ds)
    print(f"{sub:34} n={len(ds):3d}  mediana={np.median(ds):5.1f}px  "
          f"p90={np.percentile(ds,90):6.1f}  max={ds.max():6.1f}")

print("\n-- 15 mayores desviaciones --")
for d, sub, b, m in sorted(peor, reverse=True)[:15]:
    print(f"  {d:7.1f}px  {b:16} {m:9} {sub}")
