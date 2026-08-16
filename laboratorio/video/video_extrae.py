#!/usr/bin/env python
"""Extrae frames del video 4K y les aplica el mismo recorte que a las fotos.

El Sol mide 361 px en el video (240 mm, lectura 4K a todo el ancho del sensor),
frente a 563 px en las fotos de la a6400. Para que ocupe la MISMA proporcion de
cuadro que en las fotos (28,15 %), el recorte es de 1282x1282 px nativos.

Dos tramos:
  1_ocultacion       0:30 -> 6:38, muestreado con aceleracion decreciente
  2_totalidad_inicio 7:50,1 -> 7:58,5, todos los frames (tiempo real)
"""
import os, subprocess, sys, json
import numpy as np
from PIL import Image
sys.path.insert(0, '.')
import detect

Image.MAX_IMAGE_PIXELS = None
ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
V = os.path.join(ROOT, "eclipse a6400/PRIVATE/M4ROOT/CLIP/C0001.MP4")
DST = os.path.join(ROOT, "secuencias", "video_a6400")
TMP = 'vtmp'
FPS = 25.0
LADO = 1282
R_VID = 180.4
detect.R_SUN[999.0] = R_VID
detect.R_MOON[999.0] = 187.4

# ---- tramos ----
T0_OC, T1_OC = 30.0, 398.0        # creciente nitido y visible bajo el ND
N_OC = 250                        # 10 s a 25 fps
W_EASE = 0.60                     # 0 = ritmo constante, 1 = frena mucho al final
T0_TO, T1_TO = 470.16, 478.5      # anillo de totalidad, sin filtro

scan = np.load('scan.npy')        # (segundo, max, npx, cx, cy, media) a 1 fps
malos = {int(r[0]) for r in scan if r[1] < 90}          # segundos negros/debiles


def objetivos_ocultacion():
    """Instantes con aceleracion decreciente: al final avanza mas despacio."""
    fs = []
    for i in range(N_OC):
        u = i / (N_OC - 1)
        s = (1 - W_EASE) * u + W_EASE * (2 * u - u * u)   # ease-out
        t = T0_OC + s * (T1_OC - T0_OC)
        f = int(round(t * FPS))
        if int(t) in malos:                               # esquiva los negros
            for d in range(1, 40):
                if int((f + d) / FPS) not in malos:
                    f += d
                    break
        while fs and f <= fs[-1]:
            f += 1
        fs.append(f)
    return fs


def extrae_lista(frames, carpeta, hilos=5):
    """Extrae cada frame con su propia busqueda (0,7 s cada una, en paralelo).

    Una sola pasada con select= no sirve: la expresion con 250 terminos supera
    lo que admite el parser de ffmpeg.
    """
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(carpeta, exist_ok=True)

    def uno(par):
        i, f = par
        dst = os.path.join(carpeta, f'x{i:05d}.png')
        subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{f / FPS:.5f}',
                        '-i', V, '-frames:v', '1', '-y', dst],
                       check=True, stdin=subprocess.DEVNULL)
        return dst

    with ThreadPoolExecutor(hilos) as ex:
        list(ex.map(uno, enumerate(frames)))
    return sorted(os.listdir(carpeta))


def recorta(src, dst, cx, cy):
    im = Image.open(src)
    W, H = im.size
    x0, y0 = int(round(cx)) - LADO // 2, int(round(cy)) - LADO // 2
    if x0 >= 0 and y0 >= 0 and x0 + LADO <= W and y0 + LADO <= H:
        out = im.crop((x0, y0, x0 + LADO, y0 + LADO))
        cabe = True
    else:
        out = Image.new(im.mode, (LADO, LADO), 0)
        sx0, sy0 = max(0, x0), max(0, y0)
        sx1, sy1 = min(W, x0 + LADO), min(H, y0 + LADO)
        if sx1 > sx0 and sy1 > sy0:
            out.paste(im.crop((sx0, sy0, sx1, sy1)), (sx0 - x0, sy0 - y0))
        cabe = False
    out.save(dst, compress_level=6)
    return cabe


def procesa(frames, nombre):
    tmp = os.path.join(TMP, nombre)
    if os.path.isdir(tmp):
        import shutil
        shutil.rmtree(tmp)
    print(f"[{nombre}] extrayendo {len(frames)} frames del 4K...", flush=True)
    got = extrae_lista(frames, tmp)
    if len(got) != len(frames):
        print(f"  aviso: ffmpeg devolvio {len(got)} de {len(frames)}", flush=True)
    dst = os.path.join(DST, nombre)
    os.makedirs(dst, exist_ok=True)
    reg = []
    for i, (f, g) in enumerate(zip(frames, got), 1):
        src = os.path.join(tmp, g)
        r = detect.detect(src, 999.0, div=2)
        t = f / FPS
        out = os.path.join(dst, f"{i:03d}_{int(t)//60}m{t%60:05.2f}s_f{f:05d}.png")
        cabe = recorta(src, out, r['cx'], r['cy'])
        reg.append(dict(n=i, frame=f, t=round(t, 3), cx=r['cx'], cy=r['cy'],
                        metodo=r['method'], cabe=cabe))
        if i % 25 == 0:
            print(f"  {i}/{len(frames)}", flush=True)
    json.dump(reg, open(os.path.join(dst, 'registro.json'), 'w'), indent=1)
    fuera = [r for r in reg if not r['cabe']]
    print(f"[{nombre}] listo: {len(reg)} frames, con relleno negro: {len(fuera)}",
          flush=True)
    return reg


if __name__ == '__main__':
    os.makedirs(TMP, exist_ok=True)
    if 'oc' in sys.argv:
        procesa(objetivos_ocultacion(), '1_ocultacion')
    if 'to' in sys.argv:
        fr = list(range(int(round(T0_TO * FPS)), int(round(T1_TO * FPS)) + 1))
        procesa(fr, '2_totalidad_inicio')
