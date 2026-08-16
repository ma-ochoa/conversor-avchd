#!/usr/bin/env python
"""Secuencia del final del eclipse (anillo de diamantes) + fase 3.

Cada foto se vuelve a recortar desde el JPG original con el centro corregido:
se mide el desvio residual sobre el recorte que ya existe y se aplica como
correccion. Hace falta porque en los fotogramas del anillo el destello del
grano sesga el ajuste del limbo (09341 estaba a 86 px del centro y 09346 a 96,
cuando la referencia de totalidad es de 5,5 px).
"""
import os, json, sys, shutil
import numpy as np
from PIL import Image
sys.path.insert(0, '.')
import detect

ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
REC = f"{ROOT}/recortadas"
ORIG = f"{ROOT}/eclipse a6400/DCIM/100MSDCF"
DST = f"{ROOT}/secuencias/a6400/2b_anillo_y_fase3"
LADO, R = 2000, 281.6
H = LADO // 2

cent = {r['base']: r for r in json.load(open('centers.json'))}
fas = {r['file']: r for r in json.load(open('fases.json'))}

SEL = [
    # (numero, bloque, nota)
    (9339, 'anillo', 'el anillo completo, la mas limpia'),
    (9341, 'anillo', 'anillo de diamantes'),
    (9346, 'anillo', 'anillo de diamantes'),
    (9351, 'anillo', 'grano mayor'),
    (9356, 'anillo', 'AÑADIDA: gemela de 09351, un paso mas'),
    (9365, 'anillo', 'grano maximo'),
    (9349, 'puente', 'AÑADIDA: 1/4000, creciente naciendo'),
    (9357, 'puente', 'AÑADIDA: 1/4000'),
    (9363, 'puente', 'AÑADIDA: 1/4000'),
    (9369, 'puente', 'AÑADIDA: 1/4000, ultimo antes del filtro'),
    (9374, 'fase3', 'filtro puesto de nuevo'),
    (9381, 'fase3', ''),
    (9386, 'fase3', ''),
    (9389, 'fase3', ''),
    (9394, 'fase3', ''),
    (9397, 'fase3', ''),
    (9400, 'fase3', 'ultima antes de la puesta de sol'),
]


def ruta_rec(b):
    for rt, _, fs in os.walk(REC):
        if b in fs:
            return os.path.join(rt, b)


def residuo(path):
    a = np.asarray(Image.open(path).convert('L'), dtype=np.float32)
    c = a.shape[0] / 2
    for pf in (0.90, 0.70, 0.55):
        cx, cy, k, sc = detect.refine_sun_limb(a, c, c, R, photo_frac=pf)
        if k >= 100 and sc < 0.08:
            return cx - c, cy - c, k
    cx, cy, k, _ = detect.refine_limb(a, c, c, R)
    return (cx - c, cy - c, k) if k >= 60 else (0.0, 0.0, 0)


if os.path.isdir(DST):
    shutil.rmtree(DST)
os.makedirs(DST)
info = []
for i, (n, bloque, nota) in enumerate(SEL, 1):
    b = f"DSC0{n}"
    rp = ruta_rec(b + '.png')
    dx, dy, k = residuo(rp)
    cx = cent[b + '.JPG']['cx'] + dx
    cy = cent[b + '.JPG']['cy'] + dy
    im = Image.open(os.path.join(ORIG, b + '.JPG'))
    W, Hh = im.size
    x0 = min(max(int(round(cx)) - H, 0), W - LADO)
    y0 = min(max(int(round(cy)) - H, 0), Hh - LADO)
    dst = os.path.join(DST, f"{i:02d}_{bloque}_{b}.png")
    im.crop((x0, y0, x0 + LADO, y0 + LADO)).save(dst, compress_level=6)
    # verificacion sobre el recorte nuevo
    ndx, ndy, nk = residuo(dst)
    info.append(dict(n=i, foto=b, bloque=bloque, nota=nota,
                     hora=cent[b + '.JPG']['dt'][11:],
                     exp=cent[b + '.JPG']['exp'],
                     luz=round(fas[b + '.png']['media'], 1),
                     antes=round(float(np.hypot(dx, dy)), 2),
                     despues=round(float(np.hypot(ndx, ndy)), 2)))
json.dump(info, open(os.path.join(DST, 'orden.json'), 'w'), indent=1)

print(f"{'#':>3} {'foto':9}{'bloque':9}{'hora':10}{'exp':>8}{'luz':>7}"
      f"{'desvio antes':>14}{'despues':>9}")
for r in info:
    print(f"{r['n']:3d} {r['foto']:9}{r['bloque']:9}{r['hora']:10}{r['exp']:>8}"
          f"{r['luz']:7.1f}{r['antes']:12.1f}px{r['despues']:7.1f}px")
d = [r['despues'] for r in info]
print(f"\ndesvio final: mediana {np.median(d):.2f} px  max {max(d):.2f} px "
      f"(referencia de totalidad: 5,5 px de mediana)")
