#!/usr/bin/env python
"""Arma las secuencias para los videos y las deja listas para ojear en Finder.

Por cada fase:
  1) se agrupan los candidatos por instante de disparo (una horquilla = un instante)
  2) se elige UNA foto por instante con programacion dinamica, minimizando el
     salto de luz respecto a la anterior y penalizando alejarse del grupo 2_base
  3) se muestrea de forma uniforme EN TIEMPO hasta el numero de fotogramas pedido
Los archivos se copian renumerados para que el visor del sistema los muestre
en el orden de reproduccion.
"""
import json, os, math, shutil, csv, collections

ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
OUT = os.path.join(ROOT, "recortadas")
DST = os.path.join(ROOT, "secuencias")

FASES = {
    'a6400': [('1_fase_inicial', 9266, 9318, 12),
              ('2_totalidad',    9319, 9338,  8),
              ('3_fase_final',   9339, 9404, 12)],
    'a66':   [('2_totalidad',    2297, 2332, 11),
              ('3_fase_final',   2347, 2442, 12),
              ('4_puesta_de_sol', 2443, 2460, 8)],
}
PEN = {'2_base': 0.0, '1_oscuras': 0.35, '3_claras': 0.35,
       '0_muy_oscuras': 0.9, '4_muy_claras': 0.9}

# descartadas tras revisarlas una a una (ver LEEME)
DESCARTES = {
    'DSC09266.JPG': 'quemada, solo deslumbramiento',
    'DSC09343.JPG': 'quemada, se pierde el disco',
    'DSC09345.JPG': 'totalmente blanca',
    'DSC09348.JPG': 'quemada, mancha blanca',
    'DSC09401.JPG': 'movida (4 s)',
    'DSC09402.JPG': 'movida (4 s)',
    'DSC09403.JPG': 'movida (4 s)',
    'DSC09404.JPG': 'movida (4 s)',
}

cent = {r['base']: r for r in json.load(open('centers.json'))}
expo = {r['base']: r for r in json.load(open('exposicion.json'))}
fase = {r['file']: r for r in json.load(open('fases.json'))}


def seg(dt):
    h, m, s = dt.split(' ')[1].split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


def lum(b):
    return math.log2(max(fase[b.replace('.JPG', '.png')]['media'], 0.05))


def selecciona(cands, n):
    """n fotogramas repartidos en el tiempo, con la luz lo mas continua posible.

    1) Los candidatos se agrupan por INSTANTE de disparo (cada horquilla es un
       instante). Se eligen n instantes repartidos uniformemente en el tiempo,
       incluyendo siempre el primero y el ultimo de la fase: eso garantiza la
       coherencia temporal y que la fase se cubra entera.
    2) Dentro de esos instantes se decide QUE toma usar con programacion
       dinamica, minimizando el salto de luz de una foto a la siguiente y
       penalizando alejarse del grupo 2_base.

    Separar las dos decisiones es deliberado: intentar optimizar reparto
    temporal y continuidad de luz a la vez hace que una se coma a la otra
    (o se amontonan las fotos donde la luz es plana, o se pierde la fase).
    """
    inst = collections.OrderedDict()
    for b in sorted(cands, key=lambda b: (seg(cent[b]['dt']), b)):
        inst.setdefault(seg(cent[b]['dt']), []).append(b)
    tiempos = list(inst.keys())

    if len(tiempos) <= n:
        elegidos = tiempos
    else:
        t0, t1 = tiempos[0], tiempos[-1]
        elegidos, usados = [], set()
        for i in range(n):
            obj = t0 + (t1 - t0) * i / (n - 1)
            for t in sorted(tiempos, key=lambda t: (abs(t - obj), t)):
                if t not in usados:
                    usados.add(t)
                    elegidos.append(t)
                    break
        elegidos.sort()

    niveles = [inst[t] for t in elegidos]
    est = {b: PEN[expo[b]['grupo_exp']] for b in niveles[0]}
    trazas = [{b: None for b in niveles[0]}]
    for lvl in niveles[1:]:
        nv, viene = {}, {}
        for b in lvl:
            mejor, quien = None, None
            for prev, cp in est.items():
                c = cp + abs(lum(b) - lum(prev)) + PEN[expo[b]['grupo_exp']]
                if mejor is None or c < mejor:
                    mejor, quien = c, prev
            nv[b], viene[b] = mejor, quien
        est = nv
        trazas.append(viene)

    b = min(est, key=est.get)
    out = [b]
    for k in range(len(niveles) - 1, 0, -1):
        b = trazas[k][b]
        out.append(b)
    return list(reversed(out))


def ruta(base):
    for r, _, fs in os.walk(OUT):
        if base.replace('.JPG', '.png') in fs:
            return os.path.join(r, base.replace('.JPG', '.png'))
    return None


if os.path.isdir(DST):
    shutil.rmtree(DST)
resumen = []
for cam, fs in FASES.items():
    for nom, lo, hi, n in fs:
        cands = [b for b in cent
                 if cent[b]['cam'] == cam and cent[b]['grupo'] != 'no_sol'
                 and lo <= int(b[3:8]) <= hi
                 and b not in DESCARTES
                 and 'borde' not in (ruta(b) or '') and 'revisar' not in (ruta(b) or '')]
        if not cands:
            continue
        ch = selecciona(cands, n)
        d = os.path.join(DST, cam, nom)
        os.makedirs(d, exist_ok=True)
        filas = []
        for i, b in enumerate(ch, 1):
            hhmmss = cent[b]['dt'][11:].replace(':', '-')
            dst = os.path.join(d, f"{i:02d}_{hhmmss}_{b.replace('.JPG', '.png')}")
            shutil.copy2(ruta(b), dst)
            m = fase[b.replace('.JPG', '.png')]['media']
            filas.append([i, b, cent[b]['dt'][11:], cent[b]['exp'],
                          expo[b]['grupo_exp'], f"{m:.2f}"])
        with open(os.path.join(d, 'orden.txt'), 'w') as f:
            f.write(f"{cam} — {nom}   {len(ch)} fotogramas\n\n")
            f.write(f"{'#':>3}  {'archivo':16} {'hora':10} {'exposicion':>10} "
                    f"{'grupo':14} {'brillo':>7}\n")
            for r in filas:
                f.write(f"{r[0]:3d}  {r[1]:16} {r[2]:10} {r[3]:>10} {r[4]:14} {r[5]:>7}\n")
        ms = [fase[b.replace('.JPG', '.png')]['media'] for b in ch]
        salto = max(abs(math.log2(max(ms[i + 1], .05) / max(ms[i], .05)))
                    for i in range(len(ms) - 1)) if len(ms) > 1 else 0
        resumen.append((cam, nom, len(ch), cent[ch[0]]['dt'][11:], cent[ch[-1]]['dt'][11:],
                        min(ms), max(ms), salto))

print(f"{'camara':7}{'fase':17}{'n':>3}  {'desde':9}{'hasta':10}"
      f"{'brillo min':>11}{'max':>8}{'salto max':>11}")
for r in resumen:
    print(f"{r[0]:7}{r[1]:17}{r[2]:3d}  {r[3]:9}{r[4]:10}{r[5]:11.2f}{r[6]:8.2f}"
          f"{r[7]:10.1f} EV")
