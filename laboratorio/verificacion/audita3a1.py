#!/usr/bin/env python
"""Auditoria de la secuencia final: negros, movidos y descentrados.

Se comprueba sobre los PNG ya exportados, no sobre los datos intermedios:
es la unica forma de verificar lo que de verdad ha salido.
"""
import glob, os, sys, json
import numpy as np
from PIL import Image
sys.path.insert(0, '.')
import detect

D = ("/Users/maochoa/Desktop/tarjetas carmas/eclipse final/"
     "secuencias/video_a6400/ocultacion_3a1_frames")
R = 180.4
fs = sorted(glob.glob(D + '/*.png'))
print(f"auditando {len(fs)} fotogramas...", flush=True)

mx, prox, cen = [], [], []
for i, p in enumerate(fs):
    a = np.asarray(Image.open(p).convert('L'), dtype=np.float32)
    m = float(a.max())
    mx.append(m)
    if m < 32:
        prox.append(np.nan)
    else:
        nuc = int((a >= 0.5 * m).sum())
        bor = int(((a >= 0.2 * m) & (a < 0.8 * m)).sum())
        prox.append(bor / max(nuc, 1))
    if i % 5 == 0 and m >= 40:                 # centrado en 1 de cada 5
        cx, cy, n, sc = detect.refine_sun_limb(a, a.shape[1] / 2, a.shape[0] / 2, R)
        if n >= 100 and sc < 0.08:
            cen.append((i, float(np.hypot(cx - a.shape[1] / 2, cy - a.shape[0] / 2))))
    if i % 500 == 0:
        print(f"  {i}/{len(fs)}", flush=True)

mx = np.array(mx)
prox = np.array(prox)
V = 61
base = np.array([np.nanmedian(prox[max(0, i - V // 2):i + V // 2 + 1])
                 for i in range(len(prox))])
rel = prox / base

# el apagado real empieza sobre el fotograma correspondiente a 6:30
tt = np.array([float(os.path.basename(p).split('_')[1][:-1].replace('m', '')
                     .replace('.', '')) for p in fs])
idx_cola = next(i for i, p in enumerate(fs) if '6m3' in os.path.basename(p))

neg = [i for i in np.nonzero(mx < 32)[0] if i < idx_cola]
mov = [i for i in np.nonzero(rel > 1.6)[0] if i < idx_cola]
d = np.array([c[1] for c in cen])

print(f"\nRESULTADO")
print(f"  negros en mitad de la secuencia : {len(neg)}"
      + (f"  -> {[os.path.basename(fs[i])[:5] for i in neg[:10]]}" if neg else "  (ninguno)"))
print(f"  posibles movidos                : {len(mov)}"
      + (f"  -> {[os.path.basename(fs[i])[:5] for i in mov[:10]]}" if mov else "  (ninguno)"))
print(f"  descentrado (1 de cada 5, n={len(d)}):")
print(f"      mediana {np.median(d):.2f} px   p95 {np.percentile(d,95):.2f} px   "
      f"max {d.max():.2f} px   (sobre 1282 px de lado)")
peor = sorted(cen, key=lambda c: -c[1])[:5]
print(f"      peores: {[(os.path.basename(fs[i])[:5], round(v,1)) for i,v in peor]}")
json.dump(dict(neg=[int(i) for i in neg], mov=[int(i) for i in mov],
               cen=[[int(a), float(b)] for a, b in cen]),
          open('auditoria3a1.json', 'w'))
