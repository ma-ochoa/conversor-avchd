#!/usr/bin/env python
"""Secuencia completa del eclipse con FILM.

Sin normalizar la exposicion (v1). La medida por zonas mostro que el cambio de
brillo entre tomas NO es uniforme -1,22x en el limbo, 33x dentro del disco,
5,13x en el cielo lejano- asi que una ganancia global corregia el promedio y
estropeaba la corona. Ademas, en el limbo, que es donde esta el artefacto, las
tomas ya se parecen en brillo: el problema no era la exposicion sino el
contenido nuevo que hay que inventar.

Se ataca por el otro lado: densidad de intermedios segun el hueco real. Donde
FILM acierta se exprime; donde tiene que inventar se le dan pocos fotogramas
para que el defecto pase rapido por pantalla.
"""
import os, sys, glob, time, json
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import numpy as np
import tensorflow as tf
from PIL import Image

L = 1280
ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
D = f"{ROOT}/secuencias/a6400/2b_anillo_y_fase3"
T = f"{ROOT}/secuencias/video_a6400/2_totalidad_inicio"
OUT = f"{ROOT}/secuencias/3_eclipse_film"
os.makedirs(OUT, exist_ok=True)

m = tf.saved_model.load('film_model')
llam = [0]


def carga(p):
    im = Image.open(p).convert('RGB')
    if im.size != (L, L):
        im = im.resize((L, L), Image.LANCZOS)
    return np.asarray(im, dtype=np.float32)[None] / 255.0


def film(a, b):
    llam[0] += 1
    return np.clip(m({'x0': tf.constant(a), 'x1': tf.constant(b),
                      'time': tf.constant([[0.5]], dtype=tf.float32)})['image'].numpy(), 0, 1)


def recursiva(a, b, n):
    if n == 0:
        return []
    mid = film(a, b)
    return recursiva(a, mid, n - 1) + [mid] + recursiva(mid, b, n - 1)


tv = sorted(glob.glob(T + '/*.png'))
fs = sorted(glob.glob(D + '/*.png'))
v206 = [p for p in tv if os.path.basename(p).startswith('206_')][0]
v209 = [p for p in tv if os.path.basename(p).startswith('209_')][0]

# (ruta, etiqueta, profundidad de interpolacion HASTA la clave siguiente)
CLAVES = [(v206, 'video206', 2), (v209, 'video209', 2)] + \
         [(fs[i], os.path.basename(fs[i])[3:-4], d) for i, d in enumerate(
             [3,   # 09339 -> 09342   12 s
              4,   # 09342 -> 09347    1 s
              3,   # 09347 -> 09351    7 s
              4,   # 09351 -> 09356    1 s
              4,   # 09356 -> 09365    3 s
              4,   # 09365 -> 09369    1 s
              3,   # 09369 -> 09374   23 s
              2,   # 09374 -> 09381   36 s
              3,   # 09381 -> 09386    6 s
              3,   # 09386 -> 09389    6 s
              2,   # 09389 -> 09394   51 s
              2,   # 09394 -> 09397   88 s
              3,   # 09397 -> 09400   10 s
              0])]

t0 = time.time()
sec = [carga(CLAVES[0][0])]
reg = [dict(n=1, origen=CLAVES[0][1], tipo='clave')]
for i in range(len(CLAVES) - 1):
    (pa, la, prof), (pb, lb, _) = CLAVES[i], CLAVES[i + 1]
    a, b = carga(pa), carga(pb)
    ints = recursiva(a, b, prof) if prof else []
    for f in ints:
        sec.append(f)
        reg.append(dict(n=len(sec), origen=f"{la}->{lb}", tipo='FILM'))
    sec.append(b)
    reg.append(dict(n=len(sec), origen=lb, tipo='clave'))
    print(f"  {la} -> {lb}: {len(ints)} intermedios | "
          f"{llam[0]} llamadas | {time.time()-t0:.0f}s", flush=True)

for i, f in enumerate(sec, 1):
    Image.fromarray((f[0] * 255).astype(np.uint8)).save(
        os.path.join(OUT, f"{i:04d}.png"), compress_level=3)
json.dump(reg, open(os.path.join(OUT, 'registro.json'), 'w'), indent=1)
print(f"\n{len(sec)} fotogramas ({len(sec)/25:.2f} s a 25 fps) "
      f"| {llam[0]} llamadas | {time.time()-t0/60:.0f}s total")
