#!/usr/bin/env python
"""Analiza cada JPG: detecta la zona mas brillante (candidato a sol) y reporta metricas."""
import sys, os, json, glob
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
DIRS = ["eclipse a66/DCIM/100MSDCF", "eclipse a6400/DCIM/100MSDCF"]


def analyze(path):
    im = Image.open(path)
    W, H = im.size
    im.draft("L", (W // 8, H // 8))   # decodifica a ~1/8 (rapido)
    im = im.convert("L")
    a = np.asarray(im, dtype=np.float32)
    h, w = a.shape
    sx, sy = W / w, H / h

    mx = float(a.max())
    # umbral relativo al maximo
    thr = max(mx * 0.75, 60.0)
    mask = a >= thr
    n = int(mask.sum())
    if n == 0:
        return dict(file=path, W=W, H=H, max=mx, n=0)

    ys, xs = np.nonzero(mask)
    wts = a[mask] - thr + 1.0
    cx = float((xs * wts).sum() / wts.sum())
    cy = float((ys * wts).sum() / wts.sum())

    # extension del blob brillante (bounding box en px full-res)
    bw = float((xs.max() - xs.min() + 1) * sx)
    bh = float((ys.max() - ys.min() + 1) * sy)

    # dispersion: si el brillo esta repartido (paisaje/nubes) la desv. es grande
    rx = float(np.sqrt(((xs - cx) ** 2 * wts).sum() / wts.sum()))
    ry = float(np.sqrt(((ys - cy) ** 2 * wts).sum() / wts.sum()))

    # cuantos pixeles casi saturados
    nsat = int((a >= 250).sum())

    # brillo medio global (escenas nocturnas/sol aislado = muy oscuro)
    mean = float(a.mean())

    return dict(file=path, W=W, H=H, max=mx, mean=mean, n=n,
                frac=n / (w * h), cx=cx * sx, cy=cy * sy,
                bw=bw, bh=bh, rx=rx * sx, ry=ry * sy, nsat=nsat,
                dw=w, dh=h)


out = []
for d in DIRS:
    for p in sorted(glob.glob(os.path.join(ROOT, d, "*.JPG"))):
        try:
            out.append(analyze(p))
        except Exception as e:
            out.append(dict(file=p, error=str(e)))
        print(".", end="", flush=True)
print()
json.dump(out, open(sys.argv[1], "w"), indent=1)
print("total:", len(out))
