#!/usr/bin/env python
"""Nitidez del limbo en frames del video (misma medida que en las fotos)."""
import sys, os, subprocess, glob
import numpy as np
from PIL import Image
sys.path.insert(0, '.')
import detect

Image.MAX_IMAGE_PIXELS = None
V = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final/eclipse a6400/PRIVATE/M4ROOT/CLIP/C0001.MP4"
R_VID = 180.4
detect.R_SUN[999.0] = R_VID
detect.R_MOON[999.0] = 187.4
FPS = 25.0


def extrae(frame_idx, dst):
    """Extrae un frame exacto por numero de frame (sin recomprimir)."""
    t = frame_idx / FPS
    subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.5f}', '-i', V,
                    '-frames:v', '1', '-y', dst],
                   check=True, stdin=subprocess.DEVNULL)
    return dst


def nitidez(path, cx, cy, R=R_VID, nray=360):
    a = np.asarray(Image.open(path).convert('L'), dtype=np.float32)
    h, w = a.shape
    ang = np.linspace(0, 2 * np.pi, nray, endpoint=False)
    rs = np.arange(R * 0.75, R * 1.25, 0.5)
    X = np.clip(np.rint(cx + np.outer(rs, np.cos(ang))).astype(int), 0, w - 1)
    Y = np.clip(np.rint(cy + np.outer(rs, np.sin(ang))).astype(int), 0, h - 1)
    prof = a[Y, X]
    anchos = []
    for j in range(nray):
        v = prof[:, j]
        lo, hi = float(v.min()), float(v.max())
        if hi - lo < 25:
            continue
        t20, t80 = lo + .2 * (hi - lo), lo + .8 * (hi - lo)
        i20 = np.nonzero(v >= t20)[0]
        i80 = np.nonzero(v >= t80)[0]
        if not len(i20) or not len(i80):
            continue
        ww = abs(rs[i80[0]] - rs[i20[0]]) if i80[0] >= i20[0] else \
             abs(rs[i20[-1]] - rs[i80[-1]])
        if 0 < ww < R * 0.4:
            anchos.append(ww)
    return (float(np.median(anchos)) if len(anchos) >= 15 else None), len(anchos)


if __name__ == '__main__':
    os.makedirs('nit', exist_ok=True)
    segs = [float(x) for x in sys.argv[1:]]
    for s in segs:
        f = int(round(s * FPS))
        p = f'nit/f{f:06d}.png'
        if not os.path.exists(p):
            extrae(f, p)
        try:
            r = detect.detect(p, 999.0, div=2)
            n, k = nitidez(p, r['cx'], r['cy'])
        except Exception as e:
            print(f"  {s:7.2f}s  error {e}")
            continue
        print(f"  {int(s)//60}:{s%60:05.2f}  frame {f:6d}  metodo={r['method']:9} "
              f"nitidez={'n/d' if n is None else f'{n:5.2f}px'} ({k} rayos)  "
              f"centro=({r['cx']:.0f},{r['cy']:.0f})")
