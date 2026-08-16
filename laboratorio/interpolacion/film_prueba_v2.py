#!/usr/bin/env python
"""Prueba de FILM: video209 -> 09339 (anillo) -> 09342 (puente), ~1,5 s.

Interpolacion recursiva: en vez de pedir directamente t=0,1 / 0,2 / 0,3..., se
parte el hueco por la mitad una y otra vez. Cada llamada trabaja asi entre
imagenes cada vez mas parecidas, que es donde el flujo optico acierta.
n=4 -> 15 fotogramas intermedios por hueco.
"""
import os, sys, glob, time
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import numpy as np
import tensorflow as tf
from PIL import Image

L = 1280
N = 4
ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
D = f"{ROOT}/secuencias/a6400/2b_anillo_y_fase3"
T = f"{ROOT}/secuencias/video_a6400/2_totalidad_inicio"
OUT = f"{ROOT}/secuencias/prueba_film_v2"
os.makedirs(OUT, exist_ok=True)

m = tf.saved_model.load('film_model')
n_llamadas = [0]


def carga(p):
    im = Image.open(p).convert('RGB')
    if im.size != (L, L):
        im = im.resize((L, L), Image.LANCZOS)
    return np.asarray(im, dtype=np.float32)[None] / 255.0


def film(a, b):
    n_llamadas[0] += 1
    o = m({'x0': tf.constant(a), 'x1': tf.constant(b),
           'time': tf.constant([[0.5]], dtype=tf.float32)})
    return np.clip(o['image'].numpy(), 0, 1)


def recursiva(a, b, n):
    if n == 0:
        return []
    mid = film(a, b)
    return recursiva(a, mid, n - 1) + [mid] + recursiva(mid, b, n - 1)


def hueco(a, b, n):
    """Interpola A->B compensando la diferencia de exposicion.

    El flujo optico asume brillo constante: si el mismo punto es 3x mas claro
    en B que en A, el algoritmo lo interpreta como movimiento y arrastra
    pixeles oscuros sobre la zona iluminada (los grumos). Se iguala B al nivel
    de A, se interpola, y despues se devuelve el brillo con una rampa lineal.
    """
    mA, mB = float(a.mean()), float(b.mean())
    k = mA / max(mB, 1e-9)
    ints = recursiva(a, np.clip(b * k, 0, 1), n)
    salida = []
    for i, f in enumerate(ints, 1):
        t = i / (len(ints) + 1)
        salida.append(np.clip(f * (1 + (1 / k - 1) * t), 0, 1))
    return salida


tv = sorted(glob.glob(T + '/*.png'))
fs = sorted(glob.glob(D + '/*.png'))
clave = [('video209', [p for p in tv if os.path.basename(p).startswith('209_')][0]),
         ('01_anillo_09339', fs[0]),
         ('02_puente_09342', fs[1])]
print("claves:", [os.path.basename(p) for _, p in clave], flush=True)

t0 = time.time()
sec = [carga(clave[0][1])]
for i in range(len(clave) - 1):
    a, b = carga(clave[i][1]), carga(clave[i + 1][1])
    print(f"  hueco {i+1}: {clave[i][0]} -> {clave[i+1][0]}", flush=True)
    sec += hueco(a, b, N) + [b]
    print(f"    {n_llamadas[0]} llamadas, {time.time()-t0:.0f}s", flush=True)

sec += [sec[-1]] * 5          # unos fotogramas de reposo al final
for i, f in enumerate(sec, 1):
    Image.fromarray((f[0] * 255).astype(np.uint8)).save(
        os.path.join(OUT, f"{i:03d}.png"), compress_level=3)
print(f"\n{len(sec)} fotogramas ({len(sec)/25:.2f} s a 25 fps) en {time.time()-t0:.0f}s")
