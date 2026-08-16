#!/usr/bin/env python
"""Deteccion del centro del disco solar por ajuste de circulo al limbo.

Estrategia:
  1) Hough de radio fijo sobre gradientes (vota a +-R en la direccion del gradiente).
     El limbo del Sol (o de la Luna en totalidad) es un arco de radio conocido,
     asi que todos sus pixeles votan al mismo centro.
  2) Refinado: rayos desde el centro estimado, se toma el radio exterior de la
     mascara brillante y se ajusta un circulo de radio fijo a esos puntos.
  3) Fallback a centroide de brillo si el limbo no da suficiente senal.
"""
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

# radio del disco solar en px a resolucion completa (6000x4000)
# pitch = 23.5mm/6000 = 3.9167um ; radio angular del Sol 2026-08-12 = 0.004596 rad
R_SUN = {240.0: 281.6, 300.0: 352.0}
R_MOON = {240.0: 292.6, 300.0: 365.7}   # luna ~3.9% mayor (eclipse total)


def gblur(a, sigma):
    """Gaussiana separable en numpy (PIL no filtra imagenes float)."""
    if sigma <= 0:
        return a
    rad = max(1, int(round(3 * sigma)))
    x = np.arange(-rad, rad + 1, dtype=np.float32)
    k = np.exp(-(x ** 2) / (2 * sigma ** 2))
    k /= k.sum()
    p = np.pad(a, ((0, 0), (rad, rad)), mode='edge')
    out = np.apply_along_axis(lambda m: np.convolve(m, k, mode='valid'), 1, p)
    p = np.pad(out, ((rad, rad), (0, 0)), mode='edge')
    out = np.apply_along_axis(lambda m: np.convolve(m, k, mode='valid'), 0, p)
    return out.astype(np.float32)


def load_lum(path, div=4):
    im = Image.open(path)
    W, H = im.size
    im.draft('L', (W // div, H // div))
    im = im.convert('L')
    if im.size != (W // div, H // div):
        im = im.resize((W // div, H // div), Image.LANCZOS)
    return np.asarray(im, dtype=np.float32), W, H


def hough_fixed_r(a, R, blur=1.5, keep=0.04):
    """Acumulador Hough con radio fijo R (en px de 'a')."""
    h, w = a.shape
    b = gblur(a, blur)
    gy, gx = np.gradient(b)
    mag = np.hypot(gx, gy)
    n = mag.size
    k = max(200, int(n * keep))
    thr = np.partition(mag.ravel(), n - k)[n - k]
    ys, xs = np.nonzero(mag >= thr)
    m = mag[ys, xs]
    ux, uy = gx[ys, xs] / m, gy[ys, xs] / m

    acc = np.zeros((h, w), dtype=np.float32)
    for sign in (1.0, -1.0):
        cxv = np.rint(xs + sign * R * ux).astype(np.int32)
        cyv = np.rint(ys + sign * R * uy).astype(np.int32)
        ok = (cxv >= 0) & (cxv < w) & (cyv >= 0) & (cyv < h)
        np.add.at(acc, (cyv[ok], cxv[ok]), m[ok])

    acc = gblur(acc, 2.0)
    idx = int(np.argmax(acc))
    cy, cx = divmod(idx, w)
    peak = float(acc[cy, cx])
    # relacion pico/fondo -> confianza
    med = float(np.median(acc[acc > 0])) if (acc > 0).any() else 1.0
    return float(cx), float(cy), peak / max(med, 1e-6)


def bright_centroid(a, rel=0.75, floor=40.0):
    mx = float(a.max())
    thr = max(mx * rel, floor)
    mask = a >= thr
    if not mask.any():
        return a.shape[1] / 2, a.shape[0] / 2, 0.0
    ys, xs = np.nonzero(mask)
    w = a[mask] - thr + 1.0
    return float((xs * w).sum() / w.sum()), float((ys * w).sum() / w.sum()), 1.0


def refine_sun_limb(a, cx, cy, R, nray=720, iters=10, photo_frac=0.55):
    """Ajusta un circulo de radio R al limbo SOLAR.

    Un creciente fino tiene dos arcos fuertes: el limbo lunar (borde interior) y
    el limbo solar (borde exterior). Solo el segundo es el disco del Sol, asi que
    se exige que justo por dentro del borde haya fotosfera (brillo cercano al
    maximo de la escena) y que el brillo caiga hacia fuera.
    """
    h, w = a.shape
    p99 = float(np.percentile(a, 99.9))
    photo = max(p99 * photo_frac, 25.0)
    ang = np.linspace(0, 2 * np.pi, nray, endpoint=False)
    ca, sa = np.cos(ang), np.sin(ang)
    npts = 0
    for _ in range(iters):
        rs = np.linspace(R * 0.55, R * 1.45, 120)
        X = cx + np.outer(rs, ca)
        Y = cy + np.outer(rs, sa)
        inb = (X >= 0) & (X < w - 1) & (Y >= 0) & (Y < h - 1)
        xi = np.clip(np.rint(X).astype(np.int32), 0, w - 1)
        yi = np.clip(np.rint(Y).astype(np.int32), 0, h - 1)
        prof = np.where(inb, a[yi, xi], np.nan).astype(np.float32)

        d = 4                                   # medio-ancho de la ventana
        inner = np.full_like(prof, np.nan)
        outer = np.full_like(prof, np.nan)
        inner[d:-d] = np.nanmean(
            np.stack([prof[d - k: -d - k or None] for k in range(1, d + 1)]), axis=0)
        outer[d:-d] = np.nanmean(
            np.stack([prof[d + k: len(prof) - d + k] for k in range(1, d + 1)]), axis=0)
        drop = inner - outer
        ok = (inner >= photo) & (drop > max(0.05 * photo, 3.0)) & np.isfinite(drop)
        # borde solar = el cruce valido mas EXTERIOR de cada rayo
        idx = np.where(ok.any(axis=0), (len(rs) - 1) - ok[::-1].argmax(axis=0), -1)
        sel = idx >= 0
        npts = int(sel.sum())
        if npts < 50:
            return cx, cy, npts, 9.9
        r_edge = rs[idx[sel]]
        px = cx + r_edge * ca[sel]
        py = cy + r_edge * sa[sel]
        dd = np.maximum(np.hypot(px - cx, py - cy), 1e-6)
        ncx = float(np.mean(px - R * (px - cx) / dd))
        ncy = float(np.mean(py - R * (py - cy) / dd))
        if not (np.isfinite(ncx) and np.isfinite(ncy)):
            return cx, cy, 0, 9.9
        done = abs(ncx - cx) < 0.02 and abs(ncy - cy) < 0.02
        cx, cy = ncx, ncy
        if done:
            break
    # dispersion de los puntos respecto al circulo ajustado (0 = arco perfecto)
    scat = float(np.std(np.hypot(px - cx, py - cy) - R) / R)
    return cx, cy, npts, scat


def refine_limb(a, cx, cy, R, nray=720, tol=0.15, iters=8, free_r=False):
    """Ajusta un circulo al limbo, localizado como maximo |d/dr| en cada rayo.

    Sirve igual en fase parcial (caida brusca fotosfera->cielo) que en totalidad
    (subida brusca disco lunar->corona): en ambos casos el limbo es el punto de
    mayor gradiente radial, independientemente del nivel absoluto de brillo.
    """
    h, w = a.shape
    ang = np.linspace(0, 2 * np.pi, nray, endpoint=False)
    ca, sa = np.cos(ang), np.sin(ang)
    ns = 80
    Rfit = R
    npts = 0
    for it in range(iters):
        rs = np.linspace(R * (1 - tol - 0.05), R * (1 + tol + 0.05), ns)
        X = cx + np.outer(rs, ca)
        Y = cy + np.outer(rs, sa)
        inb = (X >= 0) & (X < w - 1) & (Y >= 0) & (Y < h - 1)
        xi = np.clip(np.rint(X).astype(np.int32), 0, w - 1)
        yi = np.clip(np.rint(Y).astype(np.int32), 0, h - 1)
        prof = a[yi, xi].astype(np.float32)
        prof[~inb] = np.nan
        # derivada radial suavizada
        k = np.array([1, 1, 1, 0, -1, -1, -1], dtype=np.float32)
        der = np.vstack([np.convolve(prof[:, j], k, mode='same') for j in range(nray)]).T
        der[np.isnan(der)] = 0.0
        m = np.abs(der)
        m[:4, :] = 0.0
        m[-4:, :] = 0.0
        j = np.argmax(m, axis=0)
        strength = m[j, np.arange(nray)]
        r_edge = rs[j]
        # rechaza rayos sin borde claro o fuera de la banda esperada
        smax = float(strength.max()) if strength.size else 0.0
        good = (strength > max(smax * 0.10, 2.0)) & \
               (r_edge > R * (1 - tol)) & (r_edge < R * (1 + tol))
        npts = int(good.sum())
        if npts < 60:
            return cx, cy, npts, Rfit
        px = cx + r_edge[good] * ca[good]
        py = cy + r_edge[good] * sa[good]
        if free_r:
            # ajuste algebraico de circulo (Kasa)
            A = np.c_[px, py, np.ones(px.size)]
            b = px ** 2 + py ** 2
            sol, *_ = np.linalg.lstsq(A, b, rcond=None)
            ncx, ncy = sol[0] / 2, sol[1] / 2
            Rfit = float(np.sqrt(sol[2] + ncx ** 2 + ncy ** 2))
            ncx, ncy = float(ncx), float(ncy)
        else:
            # radio fijo: minimiza sum (|p-c| - R)^2
            d = np.maximum(np.hypot(px - cx, py - cy), 1e-6)
            ncx = float(np.mean(px - R * (px - cx) / d))
            ncy = float(np.mean(py - R * (py - cy) / d))
        if not (np.isfinite(ncx) and np.isfinite(ncy)):
            return cx, cy, 0, Rfit
        done = abs(ncx - cx) < 0.02 and abs(ncy - cy) < 0.02
        cx, cy = ncx, ncy
        if done:
            break
    return cx, cy, npts, Rfit


def detect(path, focal, div=4, free_r=False):
    a, W, H = load_lum(path, div)
    Rs = R_SUN[focal] / div

    mx = float(a.max())
    sat = float((a >= 250).mean())
    hx, hy, conf = hough_fixed_r(a, Rs)
    bx, by, _ = bright_centroid(a)

    # 1) limbo generico (max |d/dr|): correcto en totalidad, puede engancharse
    #    al limbo lunar en crecientes finos
    gx_, gy_, gn, Rfit = refine_limb(a, hx, hy, Rs, free_r=free_r)
    # 2) limbo solar estricto (fotosfera por dentro): correcto en fase parcial
    ix = gx_ if gn >= 60 else hx
    iy = gy_ if gn >= 60 else hy
    # umbral estricto primero (aisla la fotosfera aunque el cielo este velado),
    # relajado despues (fotogramas oscuros donde nada llega a saturar)
    cands = []
    for pf in (0.90, 0.75, 0.55):
        r = refine_sun_limb(a, ix, iy, Rs, photo_frac=pf)
        if r[2] >= 120 and r[3] < 0.045:
            cands.append(r)
    sx_, sy_, sn, scat = min(cands, key=lambda r: r[3]) if cands else (ix, iy, 0, 9.9)

    if sn >= 120:
        cx, cy, npts, method = sx_, sy_, sn, 'sol'
    elif gn >= 60:
        cx, cy, npts, method = gx_, gy_, gn, 'luna'
    elif conf >= 8.0 and np.hypot(hx - bx, hy - by) < 3.0 * Rs:
        cx, cy, npts, method = hx, hy, gn, 'hough'
    else:
        cx, cy, npts, method = bx, by, gn, 'centroide'

    if np.hypot(cx - bx, cy - by) > 4.0 * Rs:      # incoherente con el blob
        method += '?'

    return dict(cx=cx * div, cy=cy * div, W=W, H=H, conf=conf,
                npts=npts, method=method, R=Rs * div, Rfit=Rfit * div,
                sat=sat, mx=mx, hx=hx * div, hy=hy * div, bx=bx * div, by=by * div, scat=scat,
                gn=gn, sn=sn)
