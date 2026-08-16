#!/usr/bin/env python
"""Recorta cuadrado centrado en el Sol. No toca los originales.

  a6400 (240 mm) -> 2000x2000     a66 (300 mm) -> 2500x2500
Recorte en pixeles nativos (sin reescalar) y salida PNG (sin recompresion con perdida).
El Sol queda en el centro exacto en todos los fotogramas, con el mismo tamano
relativo en ambas camaras (2000/563 = 2500/704 = 3.55 diametros solares de lado).
"""
import json, os, shutil, collections, csv, sys
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
OUT = os.path.join(ROOT, "recortadas")
LADO = {'a6400': 2000, 'a66': 2500}
SUBDIR = {('a6400', 'sol'): 'a6400_240mm',
          ('a66', 'sol'): 'a66_300mm',
          ('a66', 'puesta'): 'a66_puesta_de_sol'}

recs = json.load(open('centers.json'))

# --- fotogramas sin senal utilizable: se toma el centro de su bracket ---
by_bracket = collections.defaultdict(list)
for r in recs:
    if r['grupo'] != 'no_sol':
        by_bracket[(r['cam'], r['dt'])].append(r)

def inutil(r):
    return r['mx'] < 40 or r['sat'] > 0.40

sustituidos, revisar = [], []
for r in recs:
    if r['grupo'] == 'no_sol':
        continue
    r['fuente'] = 'detectado'
    if inutil(r):
        hermanos = [h for h in by_bracket[(r['cam'], r['dt'])] if not inutil(h)]
        if hermanos:
            xs = sorted(h['cx'] for h in hermanos)
            ys = sorted(h['cy'] for h in hermanos)
            r['cx'], r['cy'] = xs[len(xs) // 2], ys[len(ys) // 2]
            r['fuente'] = 'bracket'
            sustituidos.append(r)
        else:
            r['fuente'] = 'sin_referencia'
            revisar.append(r)

# --- recorte ---
def recorta(r, destino):
    lado = LADO[r['cam']]
    half = lado // 2
    cx, cy = int(round(r['cx'])), int(round(r['cy']))
    x0, y0 = cx - half, cy - half
    im = Image.open(r['path'])
    W, H = im.size
    cabe = x0 >= 0 and y0 >= 0 and x0 + lado <= W and y0 + lado <= H
    if cabe:
        out = im.crop((x0, y0, x0 + lado, y0 + lado))   # exacto, sin remuestreo
    else:
        out = Image.new(im.mode, (lado, lado), 0)       # relleno negro
        sx0, sy0 = max(0, x0), max(0, y0)
        sx1, sy1 = min(W, x0 + lado), min(H, y0 + lado)
        if sx1 > sx0 and sy1 > sy0:
            out.paste(im.crop((sx0, sy0, sx1, sy1)), (sx0 - x0, sy0 - y0))
    os.makedirs(destino, exist_ok=True)
    dst = os.path.join(destino, os.path.splitext(r['base'])[0] + '.png')
    out.save(dst, compress_level=6)
    return cabe, dst

os.makedirs(OUT, exist_ok=True)
filas = []
n = 0
for r in recs:
    if r['grupo'] == 'no_sol':
        d = os.path.join(OUT, 'no_es_sol')
        os.makedirs(d, exist_ok=True)
        shutil.copy2(r['path'], os.path.join(d, r['base']))   # copia: no se toca el original
        filas.append([r['base'], r['cam'], 'no_es_sol', '', '', '', '', ''])
        continue

    sub = SUBDIR[(r['cam'], r['grupo'])]
    if r['fuente'] == 'sin_referencia':
        destino = os.path.join(OUT, 'revisar', sub)
    else:
        destino = os.path.join(OUT, sub)
    cabe, dst = recorta(r, destino)
    if not cabe and r['fuente'] != 'sin_referencia':
        os.remove(dst)
        destino = os.path.join(OUT, 'borde_relleno_negro', sub)
        cabe, dst = recorta(r, destino)
    filas.append([r['base'], r['cam'], os.path.relpath(destino, OUT),
                  r['dt'], f"{r['cx']:.1f}", f"{r['cy']:.1f}",
                  r['method'], r['fuente'] + ('' if cabe else ' / relleno_negro')])
    n += 1
    if n % 20 == 0:
        print(f"  {n} recortadas", flush=True)

with open(os.path.join(OUT, 'centros.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['archivo', 'camara', 'carpeta', 'fecha_hora',
                'centro_sol_x', 'centro_sol_y', 'metodo', 'notas'])
    w.writerows(filas)

print(f"\nrecortadas: {n}")
print(f"centro tomado del bracket: {len(sustituidos)} -> {[r['base'] for r in sustituidos]}")
print(f"sin referencia (revisar):  {len(revisar)} -> {[r['base'] for r in revisar]}")
