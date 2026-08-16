#!/usr/bin/env python
"""Detecta el centro del Sol en todas las fotos y guarda centers.json."""
import json, os, glob, sys
import detect

ROOT = "/Users/maochoa/Desktop/tarjetas carmas/eclipse final"
A66 = os.path.join(ROOT, "eclipse a66/DCIM/100MSDCF")
A64 = os.path.join(ROOT, "eclipse a6400/DCIM/100MSDCF")

# clasificacion por inspeccion visual + EXIF (focal / escena)
NO_SOL = set()                                   # retratos y mariposa (a66)
for n in list(range(2391, 2397)) + list(range(2397, 2406)) + list(range(2408, 2422)):
    NO_SOL.add(f"DSC0{n}.JPG")
SUNSET = {f"DSC0{n}.JPG" for n in range(2443, 2461)}   # puesta de sol en el horizonte

exif = {}
for line in open('exif.tsv'):
    p = line.rstrip('\n').split('\t')
    if len(p) >= 5 and p[1].startswith('DSC'):
        exif[p[1]] = dict(dt=p[2], focal=p[3], exp=p[4])

out = []
for d, cam in ((A66, 'a66'), (A64, 'a6400')):
    for p in sorted(glob.glob(os.path.join(d, '*.JPG'))):
        base = os.path.basename(p)
        e = exif.get(base, {})
        foc = float(e.get('focal', '0').split()[0]) if e.get('focal') else 0.0
        if base in NO_SOL:
            grupo = 'no_sol'
        elif base in SUNSET:
            grupo = 'puesta'
        else:
            grupo = 'sol'
        rec = dict(path=p, base=base, cam=cam, grupo=grupo,
                   dt=e.get('dt', ''), focal=foc, exp=e.get('exp', ''))
        if grupo != 'no_sol':
            rec.update(detect.detect(p, foc))
        out.append(rec)
        print('.', end='', flush=True)
print()
json.dump(out, open('centers.json', 'w'), indent=1)
print('guardados', len(out))
