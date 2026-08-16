#!/usr/bin/env python
"""Pasada 3: exporta la secuencia como PNG desde el 4K original.

Usa los centros ya calculados en la pasada 2, asi que no hay que volver a
detectar nada: solo decodificar, recortar y escribir. Se parte del video
original y no del ProRes para que los pixeles sean los de la camara.
"""
import subprocess, json, os
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image

ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
V = f"{ROOT}/eclipse a6400/PRIVATE/M4ROOT/CLIP/C0001.MP4"
DST = f"{ROOT}/secuencias/video_a6400/ocultacion_3a1_frames"
W, H4, FPS = 3840, 2160, 25.0
LADO, HL = 1282, 641
F0, F1 = 750, 10562

reg = json.load(open('registro_3a1.json'))['frames']
por_frame = {r['origen']: r for r in reg}
os.makedirs(DST, exist_ok=True)

dec = subprocess.Popen(
    ['ffmpeg', '-v', 'error', '-ss', f'{F0 / FPS:.5f}', '-i', V,
     '-frames:v', str(F1 - F0 + 1), '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
    stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, bufsize=10 ** 8)

pool = ThreadPoolExecutor(4)
tareas, n, f = [], 0, F0
while True:
    b = dec.stdout.read(W * H4 * 3)
    if len(b) < W * H4 * 3:
        break
    r = por_frame.get(f)
    if r is not None:
        img = np.frombuffer(b, dtype=np.uint8).reshape(H4, W, 3)
        x0 = min(max(int(round(r['cx'])) - HL, 0), W - LADO)
        y0 = min(max(int(round(r['cy'])) - HL, 0), H4 - LADO)
        rec = np.ascontiguousarray(img[y0:y0 + LADO, x0:x0 + LADO])
        t = r['t']
        nom = f"{r['salida']:04d}_{int(t)//60}m{t%60:05.2f}s_f{r['origen']:05d}.png"
        tareas.append(pool.submit(
            lambda a, p: Image.fromarray(a).save(p, compress_level=3),
            rec, os.path.join(DST, nom)))
        n += 1
        if n % 400 == 0:
            print(f"  {n}/{len(reg)}", flush=True)
    f += 1
for t in tareas:
    t.result()
pool.shutdown()
dec.wait()
print(f"PNG escritos: {n} en {DST}")
