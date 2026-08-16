#!/usr/bin/env python
"""Hojas de contacto con marca del centroide detectado."""
import json, os, math, sys
import numpy as np
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None
d = json.load(open('analysis.json'))
d = [r for r in d if 'error' not in r]

TH = 300
COLS, ROWS = 6, 6
PER = COLS * ROWS
LBL = 26
GAMMA = float(sys.argv[1]) if len(sys.argv) > 1 else 0.55
TAG = sys.argv[2] if len(sys.argv) > 2 else 'g'

lut = bytes(int(round(255 * (i / 255) ** GAMMA)) for i in range(256))


def thumb(r):
    im = Image.open(r['file'])
    W, H = im.size
    im.draft('RGB', (W // 8, H // 8))
    im = im.convert('RGB')
    im = im.point(lut * 3)
    sc = TH / max(im.size)
    nw, nh = max(1, int(im.size[0] * sc)), max(1, int(im.size[1] * sc))
    t = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new('RGB', (TH, TH), (30, 30, 40))
    canvas.paste(t, ((TH - nw) // 2, (TH - nh) // 2))
    if 'cx' in r:
        px = (TH - nw) // 2 + r['cx'] / W * nw
        py = (TH - nh) // 2 + r['cy'] / H * nh
        dr = ImageDraw.Draw(canvas)
        dr.line([(px - 14, py), (px - 5, py)], fill=(255, 0, 0), width=2)
        dr.line([(px + 5, py), (px + 14, py)], fill=(255, 0, 0), width=2)
        dr.line([(px, py - 14), (px, py - 5)], fill=(255, 0, 0), width=2)
        dr.line([(px, py + 5), (px, py + 14)], fill=(255, 0, 0), width=2)
    return canvas


nsheets = math.ceil(len(d) / PER)
for s in range(nsheets):
    chunk = d[s * PER:(s + 1) * PER]
    sheet = Image.new('RGB', (COLS * TH, ROWS * (TH + LBL)), (12, 12, 16))
    dr = ImageDraw.Draw(sheet)
    for i, r in enumerate(chunk):
        c, rw = i % COLS, i // COLS
        x, y = c * TH, rw * (TH + LBL)
        sheet.paste(thumb(r), (x, y))
        cam = 'a66' if '/eclipse a66/' in r['file'] else 'a64'
        nm = os.path.basename(r['file']).replace('.JPG', '')[3:]
        txt = f"{cam} {nm} m{r.get('max',0):.0f} f{r.get('frac',0)*100:.2f} b{r.get('bw',0):.0f}"
        dr.text((x + 4, y + TH + 6), txt, fill=(230, 230, 210))
    out = f'sheet_{TAG}{s+1:02d}.png'
    sheet.save(out)
    print(out, len(chunk))
