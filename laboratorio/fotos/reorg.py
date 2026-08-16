#!/usr/bin/env python
"""Reparte los recortes ya generados en subcarpetas por nivel de exposicion."""
import json, os, glob, shutil, csv, collections

OUT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final/recortadas"
CARPETAS = ['a6400_240mm', 'a66_300mm', 'a66_puesta_de_sol',
            'borde_relleno_negro/a6400_240mm', 'borde_relleno_negro/a66_300mm']
GRUPOS = ['0_muy_oscuras', '1_oscuras', '2_base', '3_claras', '4_muy_claras']

exp = {r['base']: r for r in json.load(open('exposicion.json'))}
cent = {r['base']: r for r in json.load(open('centers.json'))}

movidos = collections.Counter()
sin_grupo = []
for c in CARPETAS:
    for p in glob.glob(os.path.join(OUT, c, '*.png')):
        jpg = os.path.basename(p).replace('.png', '.JPG')
        e = exp.get(jpg)
        if not e:
            sin_grupo.append(jpg)
            continue
        d = os.path.join(OUT, c, e['grupo_exp'])
        os.makedirs(d, exist_ok=True)
        shutil.move(p, os.path.join(d, os.path.basename(p)))
        movidos[(c, e['grupo_exp'])] += 1

# --- csv actualizado ---
LADO = {'a6400': 2000, 'a66': 2500}
def destino(base):
    for c in CARPETAS + ['revisar_fotograma_negro']:
        for g in GRUPOS + ['']:
            if os.path.exists(os.path.join(OUT, c, g, base.replace('.JPG', '.png'))):
                return os.path.join(c, g).rstrip('/')
        if os.path.exists(os.path.join(OUT, 'revisar_fotograma_negro',
                                       base.replace('.JPG', '.png'))):
            return 'revisar_fotograma_negro'
    return ''

viejo = {r['archivo']: r for r in csv.DictReader(open(os.path.join(OUT, 'centros.csv')))}
with open(os.path.join(OUT, 'centros.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['archivo', 'camara', 'focal', 'fecha_hora', 'exposicion', 'apertura',
                'iso', 'EV', 'EV_rel_horquilla', 'grupo_exposicion', 'grupo_escena',
                'carpeta_salida', 'lado_px', 'centro_sol_x', 'centro_sol_y',
                'metodo_deteccion', 'notas'])
    for base in sorted(cent, key=lambda b: (cent[b]['cam'], b)):
        r = cent[base]
        v = viejo.get(base, {})
        if r['grupo'] == 'no_sol':
            w.writerow([base, r['cam'], r['focal'], r['dt'], r['exp'], '', '', '', '',
                        '', 'no_es_sol', 'no_es_sol', '', '', '', '',
                        'copia del original'])
            continue
        e = exp.get(base, {})
        w.writerow([base, r['cam'], r['focal'], r['dt'], r['exp'],
                    f"f/{e.get('N','')}", int(e['iso']) if e else '',
                    f"{e['ev']:+.1f}" if e else '',
                    f"{e['ev_rel']:+.1f}" if e else '',
                    e.get('grupo_exp', ''), r['grupo'], destino(base),
                    LADO[r['cam']], f"{r['cx']:.1f}", f"{r['cy']:.1f}",
                    v.get('metodo_deteccion', ''), v.get('notas', '')])

for k in sorted(movidos):
    print(f"  {k[0]}/{k[1]:16} {movidos[k]:4d}")
print("total movidos:", sum(movidos.values()), "| sin grupo:", sin_grupo)
