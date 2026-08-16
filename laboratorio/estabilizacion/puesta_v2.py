#!/usr/bin/env python
"""Puesta de sol, bloqueo total v2: trayectoria por anclas encadenadas.

La v1 sumaba el desplazamiento fotograma a fotograma. Con 1313 sumas y 1-2 px
de error en cada una, la trayectoria se iba mas de 120 px: por eso a partir del
segundo 25 volvia a moverse.

Medir cada fotograma directamente contra el primero tampoco sirve: al ponerse
el Sol la escena cambia tanto que la calidad de la correlacion cae de 220 a 10.

Solucion: anclas cada 5 s. Las anclas se encadenan entre si (una decena de
sumas, no 1313) y cada fotograma se mide contra SU ancla, que esta a menos de
2,5 s y por tanto se le parece mucho. El error acumulado baja de ~120 px a ~20.
"""
import subprocess, json, os
import numpy as np

ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
M = f"{ROOT}/eclipse a66/PRIVATE/AVCHD/BDMV/STREAM/00000.MTS"
DST = f"{ROOT}/secuencias/a66/puesta_bloqueada_v2.mov"
W, H = 1920, 1080
AW, AH = 960, 540          # resolucion de analisis
PASO = 125                 # una ancla cada 5 s
win = np.outer(np.hanning(AH), np.hanning(AW))


def espectro(a):
    return np.fft.rfft2((a - a.mean()) * win)


def desp(Fa, Fb):
    """Desplazamiento de a respecto a b, y calidad del pico."""
    C = Fa * np.conj(Fb)
    C /= np.maximum(np.abs(C), 1e-9)
    c = np.fft.irfft2(C, s=(AH, AW))
    j = int(np.argmax(c))
    py, px = divmod(j, AW)
    if py > AH // 2: py -= AH
    if px > AW // 2: px -= AW
    return px * 2.0, py * 2.0, float(c.max() / (np.abs(c).mean() + 1e-9))


print("leyendo y desentrelazando...", flush=True)
p = subprocess.Popen(
    ['ffmpeg', '-v', 'error', '-i', M, '-vf', f'bwdif=mode=0,scale={AW}:{AH}',
     '-pix_fmt', 'gray', '-f', 'rawvideo', '-'],
    stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, bufsize=10 ** 8)
gris = []
while True:
    b = p.stdout.read(AW * AH)
    if len(b) < AW * AH:
        break
    gris.append(np.frombuffer(b, dtype=np.uint8).copy())
p.wait()
n = len(gris)
print(f"  {n} fotogramas", flush=True)

anc = list(range(0, n, PASO))
if anc[-1] != n - 1:
    anc.append(n - 1)
F = {i: espectro(gris[i].reshape(AH, AW).astype(np.float32)) for i in anc}

# cadena de anclas
pos = {anc[0]: (0.0, 0.0)}
cal = []
for k in range(1, len(anc)):
    dx, dy, q = desp(F[anc[k]], F[anc[k - 1]])
    pos[anc[k]] = (pos[anc[k - 1]][0] + dx, pos[anc[k - 1]][1] + dy)
    cal.append(q)
print(f"cadena de {len(anc)} anclas, calidad minima {min(cal):.0f}", flush=True)

# cada fotograma contra su ancla mas cercana
px = np.zeros(n); py = np.zeros(n); qs = np.zeros(n)
for i in range(n):
    a = min(anc, key=lambda x: abs(x - i))
    if i == a:
        px[i], py[i], qs[i] = pos[a][0], pos[a][1], 999.0
        continue
    dx, dy, q = desp(espectro(gris[i].reshape(AH, AW).astype(np.float32)), F[a])
    px[i], py[i], qs[i] = pos[a][0] + dx, pos[a][1] + dy, q
    if i % 300 == 0:
        print(f"  {i}/{n}", flush=True)

# filtro de mediana corto: quita picos sueltos sin introducir deriva
def medfilt(s, k=5):
    r = np.empty_like(s)
    for i in range(len(s)):
        r[i] = np.median(s[max(0, i - k // 2): i + k // 2 + 1])
    return r
px, py = medfilt(px), medfilt(py)

ax = int(np.ceil(px.max() - px.min())); ay = int(np.ceil(py.max() - py.min()))
CW, CH = W - ax, H - ay
CW -= CW % 2; CH -= CH % 2
print(f"\nrecorrido: {ax} x {ay} px -> recorte {CW}x{CH} "
      f"({100*CW*CH/(W*H):.0f}% de la imagen)")
print(f"calidad de la medida: mediana {np.median(qs[qs<999]):.0f}  "
      f"minimo {qs[qs<999].min():.0f}")

ox = np.clip(np.rint(px - px.min()), 0, W - CW).astype(int)
oy = np.clip(np.rint(py - py.min()), 0, H - CH).astype(int)

dec = subprocess.Popen(
    ['ffmpeg', '-v', 'error', '-i', M, '-vf', 'bwdif=mode=0',
     '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
    stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, bufsize=10 ** 8)
enc = subprocess.Popen(
    ['ffmpeg', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
     '-s', f'{CW}x{CH}', '-r', '25', '-i', '-',
     '-c:v', 'prores_ks', '-profile:v', '3', '-pix_fmt', 'yuv422p10le',
     '-y', DST], stdin=subprocess.PIPE)
i = 0
while True:
    b = dec.stdout.read(W * H * 3)
    if len(b) < W * H * 3:
        break
    a = np.frombuffer(b, dtype=np.uint8).reshape(H, W, 3)
    enc.stdin.write(np.ascontiguousarray(
        a[oy[i]:oy[i] + CH, ox[i]:ox[i] + CW]).tobytes())
    i += 1
enc.stdin.close(); enc.wait(); dec.wait()
json.dump(dict(px=px.tolist(), py=py.tolist(), CW=CW, CH=CH),
          open('puesta_v2.json', 'w'))
print(f"escritos {i} fotogramas en {os.path.basename(DST)}")
