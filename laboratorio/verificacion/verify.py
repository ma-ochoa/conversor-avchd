#!/usr/bin/env python
"""Recorta una ventana alrededor del centro detectado y dibuja el circulo ajustado."""
import sys, os
import numpy as np
from PIL import Image, ImageDraw
import detect

Image.MAX_IMAGE_PIXELS = None
ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
A66 = os.path.join(ROOT, "eclipse a66/DCIM/100MSDCF")
A64 = os.path.join(ROOT, "eclipse a6400/DCIM/100MSDCF")

files = []
for spec in sys.argv[2:]:
    cam, num = spec.split(':')
    d, f = (A66, 300.0) if cam == '66' else (A64, 240.0)
    pre = 'DSC0'
    files.append((os.path.join(d, f"{pre}{num}.JPG"), f, spec))

FREE = os.environ.get("FREE") == "1"
TH = 420
COLS = 6
rows = (len(files) + COLS - 1) // COLS
sheet = Image.new('RGB', (COLS * TH, rows * (TH + 26)), (12, 12, 16))
dr0 = ImageDraw.Draw(sheet)
lut = bytes(int(round(255 * (i / 255) ** 0.5)) for i in range(256))

for i, (p, foc, spec) in enumerate(files):
    r = detect.detect(p, foc, free_r=FREE)
    im = Image.open(p).convert('RGB')
    win = int(r['R'] * 2.6)
    cx, cy = r['cx'], r['cy']
    box = (int(cx - win), int(cy - win), int(cx + win), int(cy + win))
    crop = im.crop(box)              # crop fuera de limites -> negro
    crop = crop.point(lut * 3)
    crop = crop.resize((TH, TH), Image.LANCZOS)
    d = ImageDraw.Draw(crop)
    s = TH / (2 * win)
    pc = TH / 2
    rr = r['R'] * s
    d.ellipse([pc - rr, pc - rr, pc + rr, pc + rr], outline=(0, 255, 90), width=2)
    rf = r['Rfit'] * s
    d.ellipse([pc - rf, pc - rf, pc + rf, pc + rf], outline=(60, 160, 255), width=1)
    d.line([(pc - 18, pc), (pc + 18, pc)], fill=(255, 40, 40), width=1)
    d.line([(pc, pc - 18), (pc, pc + 18)], fill=(255, 40, 40), width=1)
    c, rw = i % COLS, i // COLS
    x, y = c * TH, rw * (TH + 26)
    sheet.paste(crop, (x, y))
    dr0.text((x + 4, y + TH + 7),
             f"{spec} {r['method']} n{r['npts']} Rf{r['Rfit']:.0f} ({cx:.0f},{cy:.0f})",
             fill=(230, 230, 210))
    print(f"{spec:10} {r['method']:9} npts={r['npts']:4d} conf={r['conf']:6.1f} "
          f"c=({cx:7.1f},{cy:7.1f}) R={r['R']:.0f} Rfit={r['Rfit']:.1f}")

sheet.save(sys.argv[1])
print("->", sys.argv[1])
