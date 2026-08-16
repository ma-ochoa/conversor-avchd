#!/usr/bin/env python
"""Pasada 2: elige, centra y recorta; escribe un ProRes listo para iMovie.

Por cada grupo de 3 fotogramas (pull down 3:1) se prueban los candidatos en
orden de calidad y se toma el primero que ademas pase la comprobacion fina:
ajuste del limbo convergido y recorte que cabe entero. Si ninguno pasa, el
grupo se omite (no se congela ni se inventa un fotograma).

El video se decodifica en una sola pasada por tuberia y los recortes se
escriben directamente a ffmpeg, sin PNG intermedios.
"""
import subprocess, sys, json
import numpy as np
sys.path.insert(0, '.')
import detect

ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
V = f"{ROOT}/eclipse a6400/PRIVATE/M4ROOT/CLIP/C0001.MP4"
SAL = f"{ROOT}/secuencias/video_a6400/ocultacion_completa_3a1.mov"
W, H4, FPS = 3840, 2160, 25.0
LADO, R = 1282, 180.4
HL = LADO // 2
F0, F1 = 750, 10562
F_COLA = int(415 * FPS)

grupos = json.load(open('grupos3a1.json'))
pase1 = {r['f']: r for r in json.load(open('pase1.json'))}
plan = {}
for g in grupos:
    for rank, f in enumerate(g['cand']):
        plan.setdefault(f, []).append((g['n'], rank))
gr_frames = {g['n']: g['cand'] for g in grupos}

dec = subprocess.Popen(
    ['ffmpeg', '-v', 'error', '-ss', f'{F0 / FPS:.5f}', '-i', V,
     '-frames:v', str(F1 - F0 + 1), '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
    stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, bufsize=10 ** 8)
enc = subprocess.Popen(
    ['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
     '-s', f'{LADO}x{LADO}', '-r', '25', '-i', '-',
     '-c:v', 'prores_ks', '-profile:v', '3', '-pix_fmt', 'yuv422p10le',
     '-y', SAL], stdin=subprocess.PIPE)


def _ajusta(a, sx, sy):
    for pf in (0.90, 0.70, 0.55):
        cx, cy, n, sc = detect.refine_sun_limb(a, sx, sy, R / 2, photo_frac=pf)
        if n >= 120 and sc < 0.06:
            return cx, cy
    return None


def centro(gris, semilla=None):
    """Centro del disco solar, siguiendo el fotograma anterior.

    El centroide del creciente cae en el cuerno, a ~60 px del centro real, y
    desde ahi el ajuste del limbo no converge (los puntos del limbo se salen
    de la banda de busqueda). Por eso se arranca del centro del fotograma
    anterior, que esta a pocos pixeles, y solo si eso falla se paga el Hough
    (521 ms frente a 60 ms), que si engancha desde cero.
    """
    a = gris[::2, ::2].astype(np.float32)          # 1920x1080
    if float(a.max()) < 32:
        return None
    if semilla is not None:
        r = _ajusta(a, semilla[0] / 2, semilla[1] / 2)
        if r is not None:
            return r[0] * 2, r[1] * 2
    hx, hy, conf = detect.hough_fixed_r(a, R / 2)
    r = _ajusta(a, hx, hy)
    return (r[0] * 2, r[1] * 2) if r is not None else None


# a partir de 6:30 el creciente es demasiado tenue para ajustar el limbo, pero
# la camara ya no se toca: el centro se extrapola de la deriva de los ultimos
# aciertos (~1,7 px/s, perfectamente lineal) en vez de descartar el fotograma
F_TENUE = int(390 * FPS)
import collections
hist = collections.deque(maxlen=60)


def extrapola(f):
    if len(hist) < 8:
        return None
    fs = np.array([h[0] for h in hist], dtype=float)
    return (float(np.polyval(np.polyfit(fs, [h[1] for h in hist], 1), f)),
            float(np.polyval(np.polyfit(fs, [h[2] for h in hist], 1), f)))


buf = {}
reg, saltados = [], []
ult = None
prev_c = None
f = F0
esperado = 1
while True:
    b = dec.stdout.read(W * H4 * 3)
    if len(b) < W * H4 * 3:
        break
    if f in plan:
        buf[f] = np.frombuffer(b, dtype=np.uint8).reshape(H4, W, 3)
    # cuando ya tengo los 3 candidatos del grupo esperado, lo resuelvo
    while esperado <= len(grupos) and all(c in buf for c in gr_frames[esperado]):
        g = grupos[esperado - 1]
        elegido = None
        for cand in g['cand']:
            img = buf[cand]
            gris = img[:, :, 1]
            if pase1[cand]['mx'] < 32:
                if cand < F_COLA:
                    continue                    # caida a negro en mitad: descartar
                c = extrapola(cand) or prev_c   # cola apagada de verdad
                if c is None:
                    continue
            else:
                c = centro(gris, prev_c)
                if c is None:
                    if cand < F_TENUE:
                        continue
                    c = extrapola(cand) or prev_c
                    if c is None:
                        continue
                else:
                    hist.append((cand, c[0], c[1]))
            x0, y0 = int(round(c[0])) - HL, int(round(c[1])) - HL
            if not (0 <= x0 <= W - LADO and 0 <= y0 <= H4 - LADO):
                continue
            elegido = (cand, c, img[y0:y0 + LADO, x0:x0 + LADO])
            break
        if elegido is None:
            saltados.append(g['n'])
        else:
            cand, c, rec = elegido
            enc.stdin.write(np.ascontiguousarray(rec).tobytes())
            prev_c = c
            reg.append(dict(salida=len(reg) + 1, origen=cand,
                            t=round(cand / FPS, 3), cx=round(c[0], 1),
                            cy=round(c[1], 1)))
        for cc in gr_frames[esperado]:
            buf.pop(cc, None)
        esperado += 1
        if esperado % 400 == 0:
            print(f"  grupo {esperado}/{len(grupos)}  escritos {len(reg)}", flush=True)
    f += 1

enc.stdin.close()
enc.wait()
dec.wait()
json.dump(dict(frames=reg, saltados=saltados),
          open('registro_3a1.json', 'w'), indent=1)
print(f"\nfotogramas escritos: {len(reg)}  ({len(reg)/25:.1f} s = "
      f"{int(len(reg)/25)//60}:{int(len(reg)/25)%60:02d})")
print(f"grupos omitidos: {len(saltados)}")
if reg:
    ts = np.array([r['t'] for r in reg])
    h = np.diff(ts)
    print(f"paso de metraje: mediana {np.median(h):.2f}s  mayor {h.max():.2f}s "
          f"en t={ts[int(h.argmax())]:.1f}s")
