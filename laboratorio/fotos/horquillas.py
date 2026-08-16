#!/usr/bin/env python
"""Detecta las horquillas y clasifica cada toma por nivel de exposicion.

Exposicion total  EV = log2(tiempo * ISO / f^2)   -> mayor = imagen mas clara.
No basta la velocidad: la a66 alterna f/8 y f/10 e ISO 100/1600, y la a6400
f/6.3 y f/7.1 con ISO 100/200/8000/12800.

La camara escribe SIEMPRE la toma base primero y despues las desviaciones,
asi que una horquilla nueva empieza cuando reaparece el EV de la base.
"""
import math, json, collections

def pt(s):
    s = s.strip()
    return float(s.split('/')[0]) / float(s.split('/')[1]) if '/' in s else float(s)

rows = []
for line in open('exif.tsv'):
    p = line.rstrip('\n').split('\t')
    if len(p) < 7 or not p[1].startswith('DSC'):
        continue
    try:
        t, N, iso = pt(p[4]), float(p[5]), float(p[6])
    except Exception:
        continue
    rows.append(dict(base=p[1], cam='a66' if 'a66' in p[0] else 'a6400',
                     dt=p[2], texp=p[4], N=N, iso=iso,
                     num=int(p[1][3:8]), ev=math.log2(t * iso / (N * N))))

cent = {r['base']: r for r in json.load(open('centers.json'))}
rows = [r for r in rows if cent.get(r['base'], {}).get('grupo') not in (None, 'no_sol')]
rows.sort(key=lambda r: (r['cam'], r['num']))

def seg(dt):
    h, m, s = dt.split(' ')[1].split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)

# --- agrupar en horquillas ---
# Sony escribe base, -d, +d, -2d, +2d: dentro de una horquilla cada desviacion
# nueva es igual o MAS extrema que las anteriores de su mismo lado. Cuando
# aparece una desviacion menos extrema, es que ha empezado otra horquilla.
def menos_extrema(r, cur):
    rel = r['ev'] - cur[0]['ev']
    lado = [x['ev'] - cur[0]['ev'] for x in cur[1:]
            if (x['ev'] - cur[0]['ev']) * rel > 0]
    if not lado:
        return False
    return abs(rel) < max(abs(v) for v in lado) - 0.15

brs, cur = [], []
for r in rows:
    nueva = (not cur or r['cam'] != cur[0]['cam']
             or seg(r['dt']) - seg(cur[-1]['dt']) > 4
             or r['num'] - cur[-1]['num'] > 3
             or abs(r['ev'] - cur[0]['ev']) < 0.15      # reaparece la base
             or menos_extrema(r, cur)
             or len(cur) >= 5)
    if nueva:
        if cur:
            brs.append(cur)
        cur = [r]
    else:
        cur.append(r)
if cur:
    brs.append(cur)

# --- rango de cada toma dentro de su horquilla ---
NOMBRE = {-2: '0_muy_oscuras', -1: '1_oscuras', 0: '2_base',
          1: '3_claras', 2: '4_muy_claras'}
for bi, b in enumerate(brs):
    ev0 = b[0]['ev']
    # niveles de EV DISTINTOS: si la velocidad topa en 1/4000 dos pasos de la
    # horquilla dan la misma exposicion real y deben caer en el mismo grupo
    def niveles(cond, key):
        vs = sorted({round(r['ev'] / 0.3) for r in b if cond(r['ev'])}, key=key)
        return vs
    abajo = niveles(lambda e: e < ev0 - 0.15, lambda v: v)
    arriba = niveles(lambda e: e > ev0 + 0.15, lambda v: -v)
    for r in b:
        k = round(r['ev'] / 0.3)
        if r['ev'] < ev0 - 0.15:
            r['rank'] = -2 if (len(abajo) > 1 and k == abajo[0]) else -1
        elif r['ev'] > ev0 + 0.15:
            r['rank'] = 2 if (len(arriba) > 1 and k == arriba[0]) else 1
        else:
            r['rank'] = 0
        r['grupo_exp'] = NOMBRE[r['rank']]
        r['ev_rel'] = r['ev'] - ev0
        r['n_horq'] = len(b)
        r['horquilla'] = bi

json.dump(rows, open('exposicion.json', 'w'), indent=1)

print(f"horquillas detectadas: {len(brs)}")
print("  tamanos:", dict(sorted(collections.Counter(len(b) for b in brs).items())))
print()
for cam in ('a6400', 'a66'):
    c = collections.Counter(r['grupo_exp'] for r in rows if r['cam'] == cam)
    print(f"{cam}:")
    for g in sorted(NOMBRE.values()):
        print(f"   {g:16} {c.get(g,0):4d}")
print("\nejemplo de horquillas (a6400):")
for b in brs[:2] + brs[20:23]:
    print("  " + " | ".join(f"{r['base'][3:8]} {r['texp']:>6} EV{r['ev']:+5.1f} "
                            f"{r['grupo_exp'][2:]}" for r in b))
