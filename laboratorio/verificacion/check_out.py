#!/usr/bin/env python
"""Hoja de contacto de los recortes finales con retícula central."""
import sys, os, glob, math
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None
d = sys.argv[1]
out = sys.argv[2]
files = sorted(glob.glob(os.path.join(d, '**', '*.png'), recursive=True), key=os.path.basename)
TH, COLS, LBL = 260, 10, 16
GAMMA = 1.0
rows = math.ceil(len(files) / COLS)
sheet = Image.new('RGB', (COLS * TH, rows * (TH + LBL)), (10, 10, 14))
dr0 = ImageDraw.Draw(sheet)
lut = bytes(int(round(255 * (i / 255) ** GAMMA)) for i in range(256))
for i, p in enumerate(files):
    im = Image.open(p).convert('RGB').resize((TH, TH), Image.LANCZOS).point(lut * 3)
    g = ImageDraw.Draw(im)
    c = TH // 2
    g.line([(c, 0), (c, TH)], fill=(255, 0, 0), width=1)
    g.line([(0, c), (TH, c)], fill=(255, 0, 0), width=1)
    x, y = (i % COLS) * TH, (i // COLS) * (TH + LBL)
    sheet.paste(im, (x, y))
    dr0.text((x + 3, y + TH + 3), os.path.basename(p)[3:-4], fill=(220, 220, 200))
sheet.save(out)
print(out, len(files), sheet.size)
