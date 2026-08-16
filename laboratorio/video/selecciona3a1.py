#!/usr/bin/env python
"""Ordena los 3 candidatos de cada hueco (pull down 3:1) por calidad."""
import json
import numpy as np

FPS = 25.0
F_COLA = int(415 * FPS)     # a partir de 6:55 el creciente se apaga: oscuro = valido
LADO, R = 1282, 180.4
H = LADO // 2
UMBRAL_BORDE = 1.55         # veces la mediana local

d = json.load(open('pase1.json'))
f0 = d[0]['f']
bo = np.array([r['borde'] if r['borde'] is not None else np.nan for r in d])

# mediana local: el proxy sube solo segun se afina el creciente, asi que hay
# que compararlo con su entorno, no con un umbral fijo
V = 101
base = np.full(len(bo), np.nan)
for i in range(len(bo)):
    v = bo[max(0, i - V // 2): i + V // 2 + 1]
    v = v[~np.isnan(v)]
    if len(v):
        base[i] = np.median(v)
rel = bo / base

for i, r in enumerate(d):
    r['rel'] = None if np.isnan(rel[i]) else float(rel[i])
    negro = r['mx'] < 32
    cola = r['f'] >= F_COLA
    if negro and not cola:
        r['veredicto'] = 'negro'          # caida del video en mitad de la secuencia
    elif negro and cola:
        r['veredicto'] = 'ok_oscuro'      # apagado real del final
    elif r['rel'] is not None and r['rel'] > UMBRAL_BORDE:
        r['veredicto'] = 'movido'
    elif r['cx'] is not None and not (H - R <= r['cx'] <= 3840 - H + R
                                      and H - R <= r['cy'] <= 2160 - H + R):
        r['veredicto'] = 'fuera'          # el Sol no cabe ni con margen
    else:
        r['veredicto'] = 'ok'

def coste(r):
    if r['veredicto'] == 'negro':   return 900
    if r['veredicto'] == 'fuera':   return 800
    if r['veredicto'] == 'movido':  return 500 + (r['rel'] or 9)
    if r['veredicto'] == 'ok_oscuro': return 1.0
    return r['rel'] if r['rel'] is not None else 2.0

grupos = []
for k in range(0, (len(d) // 3) * 3, 3):
    tri = d[k:k + 3]
    orden = sorted(tri, key=coste)
    grupos.append(dict(n=len(grupos) + 1,
                       cand=[t['f'] for t in orden],
                       vered=[t['veredicto'] for t in orden],
                       mejor=orden[0]['veredicto']))
json.dump(grupos, open('grupos3a1.json', 'w'))

import collections
c = collections.Counter(r['veredicto'] for r in d)
print("veredicto de los 9813 fotogramas:", dict(c))
cg = collections.Counter(g['mejor'] for g in grupos)
print(f"\ngrupos 3:1: {len(grupos)}  ({len(grupos)/25:.1f} s a 25 fps = "
      f"{int(len(grupos)/25)//60}:{int(len(grupos)/25)%60:02d})")
print("  mejor candidato de cada grupo:", dict(cg))
malos = [g for g in grupos if g['mejor'] not in ('ok', 'ok_oscuro')]
print(f"  grupos sin ningun candidato bueno: {len(malos)}")
if malos:
    print("   ->", [f"{g['cand'][0]/FPS:.1f}s" for g in malos[:25]])
