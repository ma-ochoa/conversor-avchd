#!/usr/bin/env python
"""Rehace el tramo de ocultacion del video.

Cambios respecto a la primera version:
  · llega hasta 7:02, donde el creciente ya se ha apagado del todo bajo el ND:
    el ultimo fotograma es negro de verdad, no un resto de luz
  · frena mucho mas al final (ratio 9:1 en vez de 4:1), asi el ultimo segundo
    de video cubre solo los ultimos ~12 s reales, con mucho mas detalle
  · descarta los frames movidos por la vibracion del tripode y busca
    sustitutos estables en su entorno
  · en la cola, donde el Sol ya no se detecta por falta de luz, el centro se
    extrapola del movimiento (suave y sin tocar el tripode) de los ultimos
    frames buenos
"""
import os, subprocess, sys, json, shutil
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
sys.path.insert(0, '.')
import detect, vnitidez

Image.MAX_IMAGE_PIXELS = None
ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
V = os.path.join(ROOT, "eclipse a6400/PRIVATE/M4ROOT/CLIP/C0001.MP4")
DST = os.path.join(ROOT, "secuencias", "video_a6400", "1_ocultacion")
CACHE = 'vcache'
FPS, LADO, R_VID = 25.0, 1282, 180.4
detect.R_SUN[999.0] = R_VID
detect.R_MOON[999.0] = 187.4

T0, T1 = 30.0, 422.5      # hasta negro total
N = 200                   # 8 s a 25 fps
W = 0.75                  # frenada final (ratio 9:1 entre principio y final)
NIT_MAX = 2.6             # px de transicion del limbo admitidos
H = LADO // 2


def objetivos():
    fs = []
    for i in range(N):
        u = i / (N - 1)
        s = (1 - W) * u + W * (2 * u - u * u)
        fs.append(int(round((T0 + s * (T1 - T0)) * FPS)))
    return fs


def png(f):
    p = os.path.join(CACHE, f'f{f:06d}.png')
    if not os.path.exists(p):
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{f / FPS:.5f}', '-i', V,
                        '-frames:v', '1', '-y', p], check=True,
                       stdin=subprocess.DEVNULL)
    return p


def evalua(f):
    p = png(f)
    a = np.asarray(Image.open(p).convert('L'), dtype=np.float32)
    mx = float(a.max())
    if mx < 32:                      # cola: sin senal suficiente para detectar
        return dict(f=f, mx=mx, ok=False, oscuro=True, cx=None, cy=None)
    r = detect.detect(p, 999.0, div=2)
    nit, k = vnitidez.nitidez(p, r['cx'], r['cy'])
    cabe = H <= r['cx'] <= 3840 - H and H <= r['cy'] <= 2160 - H
    ok = cabe and nit is not None and nit <= NIT_MAX and k >= 40
    return dict(f=f, mx=mx, ok=bool(ok), oscuro=False,
                cx=r['cx'], cy=r['cy'], nit=nit)


def elige(objetivo, usados, radio=90):
    """El frame estable mas cercano al objetivo."""
    for d in [0] + [x for k in range(1, radio) for x in (k, -k)]:
        f = objetivo + d
        if f in usados or not (T0 * FPS <= f <= T1 * FPS):
            continue
        e = evalua(f)
        if e['oscuro'] or e['ok']:
            return e
    return None


if __name__ == '__main__':
    os.makedirs(CACHE, exist_ok=True)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(png, objetivos()))

    elegidos, usados = [], set()
    for i, o in enumerate(objetivos(), 1):
        e = elige(o, usados)
        if e is None:
            print(f"  {i}: sin frame estable cerca de {o / FPS:.2f}s")
            continue
        usados.add(e['f'])
        elegidos.append(e)
        if i % 25 == 0:
            print(f"  evaluados {i}/{N}", flush=True)
    elegidos.sort(key=lambda e: e['f'])

    # centro para los frames oscuros: extrapolado del ultimo tramo con senal
    con = [e for e in elegidos if e['cx'] is not None]
    ult = con[-8:]
    fx = np.polyfit([e['f'] for e in ult], [e['cx'] for e in ult], 1)
    fy = np.polyfit([e['f'] for e in ult], [e['cy'] for e in ult], 1)
    for e in elegidos:
        if e['cx'] is None:
            e['cx'], e['cy'] = float(np.polyval(fx, e['f'])), float(np.polyval(fy, e['f']))
            e['extrapolado'] = True

    if os.path.isdir(DST):
        shutil.rmtree(DST)
    os.makedirs(DST)
    for i, e in enumerate(elegidos, 1):
        im = Image.open(png(e['f']))
        x0, y0 = int(round(e['cx'])) - H, int(round(e['cy'])) - H
        x0 = min(max(x0, 0), im.size[0] - LADO)
        y0 = min(max(y0, 0), im.size[1] - LADO)
        t = e['f'] / FPS
        im.crop((x0, y0, x0 + LADO, y0 + LADO)).save(
            os.path.join(DST, f"{i:03d}_{int(t)//60}m{t%60:05.2f}s_f{e['f']:05d}.png"),
            compress_level=6)
    json.dump(elegidos, open(os.path.join(DST, 'registro.json'), 'w'), indent=1)

    ts = [e['f'] / FPS for e in elegidos]
    hue = np.diff(ts)
    print(f"\nfotogramas: {len(elegidos)}  ({len(elegidos)/25:.2f} s a 25 fps)")
    print(f"tramo real: {ts[0]:.2f}s -> {ts[-1]:.2f}s")
    print(f"paso: primero {hue[0]:.2f}s  ultimo {hue[-1]:.2f}s  "
          f"mayor hueco {hue.max():.2f}s en t={ts[int(hue.argmax())]:.1f}s")
    print(f"ultimo segundo de video cubre {ts[-1]-ts[-25]:.1f}s reales")
    osc = [e for e in elegidos if e.get('extrapolado')]
    print(f"frames de la cola con centro extrapolado: {len(osc)}")
