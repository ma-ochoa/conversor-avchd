#!/usr/bin/env python
"""Evalua frames del video: nitidez del limbo, encuadre y centrado.

Sirve para (a) rellenar los huecos que dejan los frames movidos por la
vibracion del tripode y (b) mapear el desvanecimiento final bajo el ND.
"""
import os, subprocess, sys, json
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
sys.path.insert(0, '.')
import detect, vnitidez

Image.MAX_IMAGE_PIXELS = None
ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
V = os.path.join(ROOT, "eclipse a6400/PRIVATE/M4ROOT/CLIP/C0001.MP4")
FPS = 25.0
LADO = 1282
R_VID = 180.4
detect.R_SUN[999.0] = R_VID
detect.R_MOON[999.0] = 187.4
CACHE = 'vcache'


def extrae(frames, hilos=6):
    os.makedirs(CACHE, exist_ok=True)

    def uno(f):
        p = os.path.join(CACHE, f'f{f:06d}.png')
        if not os.path.exists(p):
            subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{f / FPS:.5f}',
                            '-i', V, '-frames:v', '1', '-y', p],
                           check=True, stdin=subprocess.DEVNULL)
        return p
    with ThreadPoolExecutor(hilos) as ex:
        return list(ex.map(uno, frames))


def evalua(f):
    p = os.path.join(CACHE, f'f{f:06d}.png')
    a = np.asarray(Image.open(p).convert('L'), dtype=np.float32)
    mx = float(a.max())
    if mx < 12:
        return dict(f=f, t=f / FPS, mx=mx, nit=None, cabe=False, cx=None, cy=None)
    r = detect.detect(p, 999.0, div=2)
    nit, k = vnitidez.nitidez(p, r['cx'], r['cy'])
    H = LADO // 2
    cabe = (H <= r['cx'] <= 3840 - H) and (H <= r['cy'] <= 2160 - H)
    return dict(f=f, t=f / FPS, mx=mx, nit=nit, k=k, cabe=bool(cabe),
                cx=r['cx'], cy=r['cy'], met=r['method'])


if __name__ == '__main__':
    t0, t1, paso = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
    salida = sys.argv[4]
    frames = list(range(int(t0 * FPS), int(t1 * FPS) + 1, max(1, int(paso * FPS))))
    print(f"evaluando {len(frames)} frames de {t0:.1f}s a {t1:.1f}s...", flush=True)
    extrae(frames)
    res = [evalua(f) for f in frames]
    json.dump(res, open(salida, 'w'), indent=1)
    for r in res:
        n = 'n/d' if r['nit'] is None else f"{r['nit']:5.2f}"
        print(f"  {int(r['t'])//60}:{r['t']%60:05.2f} f{r['f']:6d} max={r['mx']:4.0f} "
              f"nit={n} cabe={'si' if r['cabe'] else 'NO'} "
              f"c=({r['cx'] or 0:.0f},{r['cy'] or 0:.0f})")
