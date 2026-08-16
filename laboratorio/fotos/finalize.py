#!/usr/bin/env python
"""Aparta los fotogramas sin contenido, rehace centros.csv y escribe el LEEME."""
import json, os, csv, shutil, collections

ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
OUT = os.path.join(ROOT, "recortadas")
LADO = {'a6400': 2000, 'a66': 2500}
SUBDIR = {('a6400', 'sol'): 'a6400_240mm', ('a66', 'sol'): 'a66_300mm',
          ('a66', 'puesta'): 'a66_puesta_de_sol'}
recs = json.load(open('centers.json'))

by_bracket = collections.defaultdict(list)
for r in recs:
    if r['grupo'] != 'no_sol':
        by_bracket[(r['cam'], r['dt'])].append(r)

def inutil(r):
    return r['mx'] < 40 or r['sat'] > 0.40

for r in recs:
    if r['grupo'] == 'no_sol':
        continue
    r['fuente'] = 'detectado'
    if inutil(r):
        h = [x for x in by_bracket[(r['cam'], r['dt'])] if not inutil(x)]
        if h:
            xs = sorted(x['cx'] for x in h); ys = sorted(x['cy'] for x in h)
            r['cx'], r['cy'] = xs[len(xs) // 2], ys[len(ys) // 2]
            r['fuente'] = 'centro tomado del bracket'

# fotogramas sin ninguna informacion (negros): se apartan
SIN_CONTENIDO = {b for b in ('DSC09298.JPG', 'DSC02297.JPG')}
mov = []
for r in recs:
    if r['base'] not in SIN_CONTENIDO:
        continue
    png = os.path.splitext(r['base'])[0] + '.png'
    for sub in ('', 'borde_relleno_negro/'):
        src = os.path.join(OUT, sub + SUBDIR[(r['cam'], r['grupo'])], png)
        if os.path.exists(src):
            dst_dir = os.path.join(OUT, 'revisar_fotograma_negro')
            os.makedirs(dst_dir, exist_ok=True)
            shutil.move(src, os.path.join(dst_dir, png))
            r['fuente'] = 'fotograma negro (sin senal)'
            mov.append(png)

def carpeta(r):
    if r['grupo'] == 'no_sol':
        return 'no_es_sol'
    if r['base'] in SIN_CONTENIDO:
        return 'revisar_fotograma_negro'
    sub = SUBDIR[(r['cam'], r['grupo'])]
    lado, half = LADO[r['cam']], LADO[r['cam']] // 2
    x0, y0 = round(r['cx']) - half, round(r['cy']) - half
    cabe = x0 >= 0 and y0 >= 0 and x0 + lado <= r['W'] and y0 + lado <= r['H']
    return sub if cabe else 'borde_relleno_negro/' + sub

with open(os.path.join(OUT, 'centros.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['archivo', 'camara', 'focal', 'fecha_hora', 'exposicion', 'grupo',
                'carpeta_salida', 'lado_px', 'centro_sol_x', 'centro_sol_y',
                'metodo_deteccion', 'notas'])
    for r in sorted(recs, key=lambda r: (r['cam'], r['base'])):
        if r['grupo'] == 'no_sol':
            w.writerow([r['base'], r['cam'], r['focal'], r['dt'], r['exp'],
                        'no_es_sol', 'no_es_sol', '', '', '', '', 'copia del original'])
        else:
            w.writerow([r['base'], r['cam'], r['focal'], r['dt'], r['exp'], r['grupo'],
                        carpeta(r), LADO[r['cam']], f"{r['cx']:.1f}", f"{r['cy']:.1f}",
                        r['method'].rstrip('?'), r['fuente']])

print('apartados:', mov)
for k, v in sorted(collections.Counter(carpeta(r) for r in recs).items()):
    print(f'  {k:38} {v}')
