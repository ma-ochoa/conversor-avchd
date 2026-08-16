"""Procesos de estabilización avanzada — independientes de vid.stab.

Son las funciones que resuelven cuatro problemas que la estabilización normal no
cubre, todas puras sobre numpy (entra un fotograma, sale una medida o un recorte):

  1. Extracción de fotogramas con reducción N:1 eligiendo el MEJOR de cada grupo,
     en vez de quedarse con uno fijo.
  2. Estabilización por anclas encadenadas, que deja el encuadre clavado como con
     trípode en vez de suavizar el movimiento.
  3. Seguimiento de un objeto circular de radio conocido, para centrarlo en todos
     los fotogramas (Sol, Luna, planeta).
  4. Verificación: volver a medir sobre el RESULTADO, no sobre los cálculos
     intermedios, que es lo que descubre los fallos de verdad.

Todo se apoya en ffmpeg por tubería (sin ficheros intermedios) y en aritmética de
enteros donde se puede: la estabilización mueve el ORIGEN DEL RECORTE, así que
cada píxel de salida es un píxel original sin interpolar.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from .config import resolve_output_base
from .ffmpeg_ops import FFMPEG_BIN, FFPROBE_BIN

ADVANCED_DIR_NAME = "avanzada"

# Radio angular del Sol y la Luna en radianes (valores medios). Sirven para
# calcular el radio en píxeles a partir de la focal y el tamaño del sensor, y
# ahorrarle al usuario tener que medirlo a mano.
RADIO_ANGULAR = {"sol": 0.004650, "luna": 0.004655}
SENSORES_MM = {"aps-c": 23.5, "micro43": 17.3, "full-frame": 36.0, "1inch": 13.2}


class DepsMissingError(RuntimeError):
    """numpy/Pillow no están instalados — igual que ToolsMissingError con ffmpeg."""


def check_deps() -> None:
    faltan = []
    try:
        import numpy  # noqa: F401
    except ImportError:
        faltan.append("numpy")
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        faltan.append("Pillow")
    if faltan:
        raise DepsMissingError(
            f"Falta {' y '.join(faltan)} para los procesos avanzados. Instálalo con:\n"
            f"  pip install {' '.join(faltan)}"
        )


def advanced_output_dir(root: Path, nombre: str) -> Path:
    """Carpeta de salida, respetando la carpeta de trabajo global de Ajustes."""
    base = resolve_output_base(Path(root).expanduser().resolve()) / ADVANCED_DIR_NAME
    destino = base / nombre
    destino.mkdir(parents=True, exist_ok=True)
    return destino


# --------------------------------------------------------------------------- #
#  Lectura de vídeo por tubería
# --------------------------------------------------------------------------- #

def probe_video(source: Path) -> dict:
    """Ancho, alto, fps y número de fotogramas. nb_frames puede faltar en AVCHD,
    así que se estima con la duración cuando no viene."""
    cmd = [FFPROBE_BIN, "-v", "error", "-select_streams", "v:0", "-show_entries",
           "stream=width,height,r_frame_rate,nb_frames",
           "-show_entries", "format=duration", "-of", "json", str(source)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    st = data["streams"][0]
    num, den = (st.get("r_frame_rate") or "25/1").split("/")
    fps = float(num) / float(den or 1)
    dur = float(data.get("format", {}).get("duration") or 0)
    nb = st.get("nb_frames")
    total = int(nb) if nb and nb.isdigit() else int(round(dur * fps))
    return {"width": int(st["width"]), "height": int(st["height"]),
            "fps": fps, "frames": total, "duration": dur}


def _abrir(source: Path, vf: str, pix: str, ancho: int, alto: int, bytes_px: int):
    """Proceso ffmpeg que escupe fotogramas crudos por stdout."""
    cmd = [FFMPEG_BIN, "-v", "error", "-i", str(source)]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-pix_fmt", pix, "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL,
                            bufsize=10 ** 8)
    return proc, ancho * alto * bytes_px


def leer_gris(source: Path, ancho: int, alto: int, deinterlace: bool = False):
    """Generador de fotogramas en gris, reescalados. Para medir, no para exportar."""
    import numpy as np
    filtros = ["bwdif=mode=0"] if deinterlace else []
    filtros.append(f"scale={ancho}:{alto}")
    proc, n = _abrir(source, ",".join(filtros), "gray", ancho, alto, 1)
    try:
        while True:
            b = proc.stdout.read(n)
            if len(b) < n:
                break
            yield np.frombuffer(b, dtype=np.uint8).reshape(alto, ancho)
    finally:
        proc.stdout.close()
        proc.wait()


def leer_rgb(source: Path, ancho: int, alto: int, deinterlace: bool = False):
    """Generador de fotogramas en color a resolución nativa, para exportar."""
    import numpy as np
    vf = "bwdif=mode=0" if deinterlace else ""
    proc, n = _abrir(source, vf, "rgb24", ancho, alto, 3)
    try:
        while True:
            b = proc.stdout.read(n)
            if len(b) < n:
                break
            yield np.frombuffer(b, dtype=np.uint8).reshape(alto, ancho, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def abrir_encoder(dest: Path, ancho: int, alto: int, fps: float, formato: str = "prores"):
    """ffmpeg que recibe fotogramas crudos y escribe el archivo final."""
    cmd = [FFMPEG_BIN, "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{ancho}x{alto}", "-r", f"{fps:.6f}", "-i", "-"]
    if formato == "prores":
        cmd += ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"]
    else:
        cmd += ["-c:v", "libx264", "-crf", "16", "-preset", "slow",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    cmd += ["-y", str(dest)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)


# --------------------------------------------------------------------------- #
#  1. Medida de todos los fotogramas
# --------------------------------------------------------------------------- #

def medir_fotogramas(source: Path, progress_cb=None, deinterlace: bool = False) -> list[dict]:
    """Recorre el vídeo entero y saca de cada fotograma métricas baratas.

    De aquí salen los dos filtros de calidad:
      · `mx` (máximo) detecta caídas a negro del propio vídeo
      · `borde` = píxeles en transición / píxeles de núcleo, que es un proxy de
        nitidez. NO se puede juzgar con un umbral fijo: en material que cambia de
        contraste sube o baja por sí solo. Se compara con la mediana local en
        `clasificar()`, que es lo que separa la movida real de la evolución
        natural de la escena.
    """
    import numpy as np
    info = probe_video(source)
    aw = 960
    ah = max(2, int(round(aw * info["height"] / info["width"])) // 2 * 2)
    total = max(1, info["frames"])
    res = []
    for i, a in enumerate(leer_gris(source, aw, ah, deinterlace)):
        f = a.astype(np.float32)
        mx = float(f.max())
        if mx < 12:
            res.append({"n": i, "mx": mx, "media": float(f.mean()),
                        "cx": None, "cy": None, "borde": None})
        else:
            nucleo = f >= 0.5 * mx
            k = int(nucleo.sum())
            ys, xs = np.nonzero(nucleo)
            bor = int(((f >= 0.2 * mx) & (f < 0.8 * mx)).sum())
            res.append({"n": i, "mx": mx, "media": float(f.mean()),
                        "cx": float(xs.mean()) * info["width"] / aw,
                        "cy": float(ys.mean()) * info["height"] / ah,
                        "borde": bor / max(k, 1)})
        if progress_cb and i % 25 == 0:
            progress_cb(min(1.0, i / total))
    if progress_cb:
        progress_cb(1.0)
    return res


def clasificar(medidas: list[dict], umbral_negro: float = 32.0,
               umbral_borde: float = 1.55, ventana: int = 101) -> list[dict]:
    """Marca cada fotograma como ok / negro / movido.

    El umbral de nitidez es RELATIVO a la mediana local, no absoluto: un umbral
    fijo daría falsos positivos en cuanto la escena cambia de contraste."""
    import numpy as np
    bo = np.array([m["borde"] if m["borde"] is not None else np.nan for m in medidas])
    base = np.full(len(bo), np.nan)
    mitad = ventana // 2
    for i in range(len(bo)):
        v = bo[max(0, i - mitad): i + mitad + 1]
        v = v[~np.isnan(v)]
        if len(v):
            base[i] = np.median(v)
    rel = bo / base
    for i, m in enumerate(medidas):
        m["rel"] = None if np.isnan(rel[i]) else float(rel[i])
        if m["mx"] < umbral_negro:
            m["veredicto"] = "negro"
        elif m["rel"] is not None and m["rel"] > umbral_borde:
            m["veredicto"] = "movido"
        else:
            m["veredicto"] = "ok"
    return medidas


def _coste(m: dict) -> float:
    if m["veredicto"] == "negro":
        return 900.0
    if m["veredicto"] == "movido":
        return 500.0 + (m["rel"] or 9.0)
    return m["rel"] if m["rel"] is not None else 2.0


def agrupar_pulldown(medidas: list[dict], ratio: int) -> list[list[dict]]:
    """Grupos de `ratio` fotogramas, ordenados por calidad dentro de cada grupo.

    Con 3:1 hay tres candidatos por hueco, así que en los momentos malos (una
    sacudida, una caída de señal) casi siempre queda alguno aprovechable."""
    grupos = []
    for k in range(0, (len(medidas) // ratio) * ratio, ratio):
        grupos.append(sorted(medidas[k:k + ratio], key=_coste))
    return grupos


# --------------------------------------------------------------------------- #
#  2. Extracción de fotogramas
# --------------------------------------------------------------------------- #

def extraer_fotogramas(source: Path, dest_dir: Path, ratio: int = 1,
                       descartar_negros: bool = True, descartar_movidos: bool = True,
                       salida: str = "png", deinterlace: bool = False,
                       progress_cb=None) -> dict:
    """Reducción N:1 quedándose con el mejor fotograma de cada grupo.

    Con ratio=1 no reduce: solo filtra los fotogramas malos.
    `salida` puede ser "png" (secuencia suelta) o "prores"/"h264" (vídeo)."""
    check_deps()
    import numpy as np
    from PIL import Image

    info = probe_video(source)
    if progress_cb:
        progress_cb(0.0, "midiendo fotogramas")
    medidas = clasificar(medir_fotogramas(
        source, lambda f: progress_cb and progress_cb(f * 0.45, "midiendo fotogramas"),
        deinterlace))
    grupos = agrupar_pulldown(medidas, max(1, ratio))

    elegidos: dict[int, dict] = {}
    omitidos = 0
    for g in grupos:
        pick = None
        for cand in g:
            if descartar_negros and cand["veredicto"] == "negro":
                continue
            if descartar_movidos and cand["veredicto"] == "movido":
                continue
            pick = cand
            break
        if pick is None:
            omitidos += 1
            continue
        elegidos[pick["n"]] = pick

    dest_dir.mkdir(parents=True, exist_ok=True)
    enc = None
    if salida != "png":
        enc = abrir_encoder(dest_dir / f"{source.stem}_{ratio}a1.mov",
                            info["width"], info["height"],
                            info["fps"] / max(1, ratio), salida)

    escritos = 0
    total = max(1, len(elegidos))
    for i, frame in enumerate(leer_rgb(source, info["width"], info["height"], deinterlace)):
        if i not in elegidos:
            continue
        if enc is not None:
            enc.stdin.write(np.ascontiguousarray(frame).tobytes())
        else:
            t = i / info["fps"]
            nombre = f"{escritos + 1:05d}_{int(t)//60:d}m{t % 60:05.2f}s_f{i:06d}.png"
            Image.fromarray(frame).save(dest_dir / nombre, compress_level=3)
        escritos += 1
        if progress_cb and escritos % 20 == 0:
            progress_cb(0.45 + 0.55 * escritos / total, "escribiendo")
    if enc is not None:
        enc.stdin.close()
        enc.wait()

    negros = sum(1 for m in medidas if m["veredicto"] == "negro")
    movidos = sum(1 for m in medidas if m["veredicto"] == "movido")
    return {"fotogramas_origen": len(medidas), "grupos": len(grupos),
            "escritos": escritos, "grupos_omitidos": omitidos,
            "negros_detectados": negros, "movidos_detectados": movidos,
            "duracion_s": round(escritos / (info["fps"] / max(1, ratio)), 2),
            "destino": str(dest_dir)}


# --------------------------------------------------------------------------- #
#  3. Estabilización por anclas encadenadas
# --------------------------------------------------------------------------- #

def _espectro(a, win):
    import numpy as np
    return np.fft.rfft2((a.astype(np.float32) - a.mean()) * win)


def _desplazamiento(Fa, Fb, alto, ancho, escala):
    """Correlación de fase: devuelve el desplazamiento de A respecto a B y la
    calidad del pico (relación pico/fondo), que sirve para descartar medidas."""
    import numpy as np
    C = Fa * np.conj(Fb)
    C /= np.maximum(np.abs(C), 1e-9)
    c = np.fft.irfft2(C, s=(alto, ancho))
    j = int(np.argmax(c))
    py, px = divmod(j, ancho)
    if py > alto // 2:
        py -= alto
    if px > ancho // 2:
        px -= ancho
    return px * escala, py * escala, float(c.max() / (np.abs(c).mean() + 1e-9))


def medir_trayectoria(source: Path, anclas_seg: float = 5.0, progress_cb=None,
                      deinterlace: bool = False) -> dict:
    """Recorrido de la cámara por ANCLAS ENCADENADAS.

    Por qué así y no de otra forma, que costó descubrirlo:
      · Sumar el desplazamiento fotograma a fotograma acumula el error de cada
        medida. Con 1300 fotogramas y 1-2 px de error, la trayectoria se va más
        de 120 px y el encuadre vuelve a moverse a mitad del clip.
      · Medir todo contra el primer fotograma no acumula, pero falla en cuanto la
        escena cambia (un atardecer, una luz que se va): la calidad del pico se
        desploma y las medidas se vuelven basura.
      · Anclas cada pocos segundos: las anclas se encadenan entre sí (una decena
        de sumas, no mil) y cada fotograma se mide contra SU ancla, que está cerca
        y se le parece. El error acumulado baja de ~120 px a ~20.
    """
    check_deps()
    import numpy as np
    info = probe_video(source)
    aw = 960
    ah = max(2, int(round(aw * info["height"] / info["width"])) // 2 * 2)
    escala = info["width"] / aw
    win = np.outer(np.hanning(ah), np.hanning(aw))

    grises = [a.copy() for a in leer_gris(source, aw, ah, deinterlace)]
    n = len(grises)
    if n < 2:
        raise RuntimeError("El vídeo no tiene fotogramas suficientes.")

    paso = max(2, int(round(anclas_seg * info["fps"])))
    anclas = list(range(0, n, paso))
    if anclas[-1] != n - 1:
        anclas.append(n - 1)
    F = {i: _espectro(grises[i], win) for i in anclas}

    pos = {anclas[0]: (0.0, 0.0)}
    cal_anclas = []
    for k in range(1, len(anclas)):
        dx, dy, q = _desplazamiento(F[anclas[k]], F[anclas[k - 1]], ah, aw, escala)
        pos[anclas[k]] = (pos[anclas[k - 1]][0] + dx, pos[anclas[k - 1]][1] + dy)
        cal_anclas.append(q)

    px = np.zeros(n)
    py = np.zeros(n)
    qs = np.zeros(n)
    for i in range(n):
        a = min(anclas, key=lambda x: abs(x - i))
        if i == a:
            px[i], py[i], qs[i] = pos[a][0], pos[a][1], 999.0
        else:
            dx, dy, q = _desplazamiento(_espectro(grises[i], win), F[a], ah, aw, escala)
            px[i], py[i], qs[i] = pos[a][0] + dx, pos[a][1] + dy, q
        if progress_cb and i % 25 == 0:
            progress_cb(i / n)
    if progress_cb:
        progress_cb(1.0)
    return {"px": px.tolist(), "py": py.tolist(), "calidad": qs.tolist(),
            "fotogramas": n, "info": info,
            "calidad_anclas_min": float(min(cal_anclas)) if cal_anclas else 999.0}


def _mediana_movil(s, k: int):
    import numpy as np
    r = np.empty_like(s)
    mitad = k // 2
    for i in range(len(s)):
        r[i] = np.median(s[max(0, i - mitad): i + mitad + 1])
    return r


def estabilizar_bloqueo(source: Path, dest: Path, modo: str = "bloqueo",
                        suavizado_seg: float = 1.0, anclas_seg: float = 5.0,
                        calidad_min: float = 30.0, recorte_extra: float = 0.0,
                        deinterlace: bool = False, formato: str = "prores",
                        progress_cb=None) -> dict:
    """Estabiliza moviendo el origen del recorte — sin remuestrear ni un píxel.

    modo="bloqueo": corrige TODO el recorrido, el encuadre queda clavado como con
    trípode. Cuesta más recorte pero es lo que hace falta cuando el sujeto tiene
    que quedarse quieto.
    modo="suavizado": corrige solo la diferencia respecto a la trayectoria suave,
    así que respeta el movimiento lento intencionado (un paneo, seguir al sujeto).
    """
    check_deps()
    import numpy as np

    if progress_cb:
        progress_cb(0.0, "midiendo el recorrido")
    tr = medir_trayectoria(source, anclas_seg,
                           lambda f: progress_cb and progress_cb(f * 0.5, "midiendo el recorrido"),
                           deinterlace)
    info = tr["info"]
    px = np.array(tr["px"])
    py = np.array(tr["py"])
    qs = np.array(tr["calidad"])

    # Las medidas poco fiables (escena sin rasgos, cambio brusco de luz) producen
    # saltos imposibles. Se descartan y se rellenan interpolando desde las buenas.
    ok = qs >= calidad_min
    bx, by = _mediana_movil(px, 15), _mediana_movil(py, 15)
    ok &= np.hypot(px - bx, py - by) < 45
    descartadas = int((~ok).sum())
    if ok.sum() < 2:
        raise RuntimeError("No hay medidas fiables: el vídeo no tiene bastante detalle.")
    idx = np.arange(len(px))
    px = np.interp(idx, idx[ok], px[ok])
    py = np.interp(idx, idx[ok], py[ok])

    if modo == "suavizado":
        k = max(3, int(round(suavizado_seg * info["fps"])) | 1)
        suave_x = np.convolve(np.pad(px, k // 2, mode="edge"), np.ones(k) / k, "valid")[:len(px)]
        suave_y = np.convolve(np.pad(py, k // 2, mode="edge"), np.ones(k) / k, "valid")[:len(py)]
        rx, ry = px - suave_x, py - suave_y
    else:
        rx, ry = px - px.min(), py - py.min()

    margen = 1.0 + max(0.0, recorte_extra)
    ax = int(math.ceil((rx.max() - rx.min()) * margen))
    ay = int(math.ceil((ry.max() - ry.min()) * margen))
    cw = max(16, (info["width"] - ax)) // 2 * 2
    ch = max(16, (info["height"] - ay)) // 2 * 2

    ox = np.clip(np.rint(rx - rx.min()), 0, info["width"] - cw).astype(int)
    oy = np.clip(np.rint(ry - ry.min()), 0, info["height"] - ch).astype(int)

    dest.parent.mkdir(parents=True, exist_ok=True)
    enc = abrir_encoder(dest, cw, ch, info["fps"], formato)
    i = 0
    for frame in leer_rgb(source, info["width"], info["height"], deinterlace):
        j = min(i, len(ox) - 1)
        enc.stdin.write(np.ascontiguousarray(
            frame[oy[j]:oy[j] + ch, ox[j]:ox[j] + cw]).tobytes())
        i += 1
        if progress_cb and i % 25 == 0:
            progress_cb(0.5 + 0.5 * i / max(1, tr["fotogramas"]), "escribiendo")
    enc.stdin.close()
    enc.wait()

    return {"fotogramas": i, "recorte": f"{cw}x{ch}",
            "porcentaje_imagen": round(100 * cw * ch / (info["width"] * info["height"])),
            "recorrido_px": f"{int(rx.max() - rx.min())}x{int(ry.max() - ry.min())}",
            "medidas_descartadas": descartadas,
            "calidad_anclas_min": round(tr["calidad_anclas_min"], 1),
            "destino": str(dest)}


# --------------------------------------------------------------------------- #
#  4. Seguimiento de objeto circular
# --------------------------------------------------------------------------- #

def radio_px(focal_mm: float, sensor_mm: float, ancho_px: int, objeto: str = "sol") -> float:
    """Radio del disco en píxeles a partir de la óptica, para no medirlo a mano."""
    paso_mm = sensor_mm / ancho_px
    return focal_mm * RADIO_ANGULAR.get(objeto, RADIO_ANGULAR["sol"]) / paso_mm


def ajustar_disco(a, cx: float, cy: float, R: float, nrayos: int = 720,
                  iteraciones: int = 8):
    """Ajusta una circunferencia de radio R al borde del objeto.

    Lanza rayos desde el centro estimado y busca en cada uno el punto de mayor
    gradiente radial, que es donde está el borde. Con radio FIJO (no libre) el
    ajuste es estable aunque solo se vea un arco del objeto — el caso de un disco
    parcialmente tapado o recortado por el encuadre.
    """
    import numpy as np
    alto, ancho = a.shape
    ang = np.linspace(0, 2 * np.pi, nrayos, endpoint=False)
    ca, sa = np.cos(ang), np.sin(ang)
    npts = 0
    for _ in range(iteraciones):
        rs = np.linspace(R * 0.80, R * 1.20, 80)
        X = cx + np.outer(rs, ca)
        Y = cy + np.outer(rs, sa)
        dentro = (X >= 0) & (X < ancho - 1) & (Y >= 0) & (Y < alto - 1)
        xi = np.clip(np.rint(X).astype(np.int32), 0, ancho - 1)
        yi = np.clip(np.rint(Y).astype(np.int32), 0, alto - 1)
        prof = np.where(dentro, a[yi, xi], np.nan).astype(np.float32)
        k = np.array([1, 1, 1, 0, -1, -1, -1], dtype=np.float32)
        der = np.vstack([np.convolve(prof[:, j], k, mode="same") for j in range(nrayos)]).T
        der[np.isnan(der)] = 0.0
        m = np.abs(der)
        m[:4, :] = 0.0
        m[-4:, :] = 0.0
        j = np.argmax(m, axis=0)
        fuerza = m[j, np.arange(nrayos)]
        r_borde = rs[j]
        smax = float(fuerza.max()) if fuerza.size else 0.0
        bueno = fuerza > max(smax * 0.10, 2.0)
        npts = int(bueno.sum())
        if npts < 60:
            return cx, cy, npts
        pxx = cx + r_borde[bueno] * ca[bueno]
        pyy = cy + r_borde[bueno] * sa[bueno]
        d = np.maximum(np.hypot(pxx - cx, pyy - cy), 1e-6)
        ncx = float(np.mean(pxx - R * (pxx - cx) / d))
        ncy = float(np.mean(pyy - R * (pyy - cy) / d))
        if not (np.isfinite(ncx) and np.isfinite(ncy)):
            return cx, cy, 0
        fin = abs(ncx - cx) < 0.05 and abs(ncy - cy) < 0.05
        cx, cy = ncx, ncy
        if fin:
            break
    return cx, cy, npts


def _semilla_brillo(a, umbral_rel: float = 0.75):
    import numpy as np
    mx = float(a.max())
    if mx < 20:
        return None
    m = a >= max(mx * umbral_rel, 30.0)
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    return float(xs.mean()), float(ys.mean())


def seguir_objeto(source: Path, dest: Path, radio: float, lado: int | None = None,
                  formato: str = "prores", deinterlace: bool = False,
                  progress_cb=None) -> dict:
    """Recorta cuadrado centrado en el objeto, fotograma a fotograma.

    El centro se sigue desde el fotograma anterior: entre fotogramas contiguos el
    objeto apenas se mueve, así que el ajuste engancha a la primera. Cuando falla
    (una caída de señal, el objeto tapado) se extrapola de la deriva reciente en
    vez de descartar el fotograma, porque en un plano fijo esa deriva es limpia.
    """
    check_deps()
    import numpy as np

    info = probe_video(source)
    if lado is None:
        lado = int(round(radio * 2 / 0.2815))          # el objeto ocupa ~28% del cuadro
    lado = min(lado // 2 * 2, min(info["width"], info["height"]))
    mitad = lado // 2

    dest.parent.mkdir(parents=True, exist_ok=True)
    enc = abrir_encoder(dest, lado, lado, info["fps"], formato)

    prev = None
    hist: list[tuple[int, float, float]] = []
    escritos = seguidos = extrapolados = 0
    for i, frame in enumerate(leer_rgb(source, info["width"], info["height"], deinterlace)):
        gris = frame[:, :, 1].astype(np.float32)
        centro = None
        semilla = prev or _semilla_brillo(gris)
        if semilla is not None:
            cx, cy, npts = ajustar_disco(gris, semilla[0], semilla[1], radio)
            if npts >= 60:
                centro = (cx, cy)
                hist.append((i, cx, cy))
                hist[:] = hist[-60:]
                seguidos += 1
        if centro is None and len(hist) >= 8:
            fs = np.array([h[0] for h in hist], dtype=float)
            centro = (float(np.polyval(np.polyfit(fs, [h[1] for h in hist], 1), i)),
                      float(np.polyval(np.polyfit(fs, [h[2] for h in hist], 1), i)))
            extrapolados += 1
        if centro is None:
            centro = prev or (info["width"] / 2, info["height"] / 2)

        x0 = int(min(max(round(centro[0]) - mitad, 0), info["width"] - lado))
        y0 = int(min(max(round(centro[1]) - mitad, 0), info["height"] - lado))
        enc.stdin.write(np.ascontiguousarray(frame[y0:y0 + lado, x0:x0 + lado]).tobytes())
        prev = centro
        escritos += 1
        if progress_cb and escritos % 25 == 0:
            progress_cb(escritos / max(1, info["frames"]), "siguiendo el objeto")
    enc.stdin.close()
    enc.wait()
    return {"fotogramas": escritos, "lado": lado, "radio_px": round(radio, 1),
            "seguidos": seguidos, "extrapolados": extrapolados,
            "destino": str(dest)}


# --------------------------------------------------------------------------- #
#  5. Verificación
# --------------------------------------------------------------------------- #

def hoja_contacto(origen: Path, dest: Path, columnas: int = 10, celda: int = 240,
                  reticula: bool = True, maximo: int = 400) -> dict:
    """Miniaturas en cuadrícula con retícula central, para revisar cientos de
    fotogramas de un vistazo. Acepta una carpeta de imágenes o un vídeo."""
    check_deps()
    from PIL import Image, ImageDraw

    if origen.is_dir():
        rutas = sorted([p for p in origen.iterdir()
                        if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
        cargar = lambda p: Image.open(p).convert("RGB")            # noqa: E731
        etiquetas = [p.stem[:18] for p in rutas]
    else:
        info = probe_video(origen)
        import numpy as np
        paso = max(1, info["frames"] // maximo)
        rutas, etiquetas = [], []
        for i, a in enumerate(leer_rgb(origen, info["width"], info["height"])):
            if i % paso:
                continue
            rutas.append(Image.fromarray(a.copy()))
            etiquetas.append(f"{i/info['fps']:.1f}s")
        cargar = lambda im: im                                      # noqa: E731

    rutas = rutas[:maximo]
    etiquetas = etiquetas[:len(rutas)]
    if not rutas:
        raise RuntimeError("No hay imágenes que montar.")

    filas = (len(rutas) + columnas - 1) // columnas
    hoja = Image.new("RGB", (columnas * celda, filas * (celda + 16)), (16, 16, 20))
    dib = ImageDraw.Draw(hoja)
    for i, item in enumerate(rutas):
        im = cargar(item).resize((celda, celda), Image.LANCZOS)
        if reticula:
            g = ImageDraw.Draw(im)
            c = celda // 2
            g.line([(c, 0), (c, celda)], fill=(255, 0, 0))
            g.line([(0, c), (celda, c)], fill=(255, 0, 0))
        x, y = (i % columnas) * celda, (i // columnas) * (celda + 16)
        hoja.paste(im, (x, y))
        dib.text((x + 4, y + celda + 3), etiquetas[i], fill=(230, 230, 210))
    dest.parent.mkdir(parents=True, exist_ok=True)
    hoja.save(dest, quality=88)
    return {"miniaturas": len(rutas), "destino": str(dest)}


def auditar(origen: Path, radio: float | None = None, progress_cb=None) -> dict:
    """Vuelve a medir SOBRE EL RESULTADO, no sobre los cálculos intermedios.

    Es lo que descubre los fallos de verdad: fotogramas malos que se colaron,
    deriva que reaparece a mitad del clip, descentrados que los datos intermedios
    daban por buenos."""
    check_deps()
    import numpy as np

    info = probe_video(origen)
    aw = 720
    ah = max(2, int(round(aw * info["height"] / info["width"])) // 2 * 2)
    escala = info["width"] / aw
    win = np.outer(np.hanning(ah), np.hanning(aw))

    prev = ref = None
    consec, absol, descentr = [], [], []
    n = 0
    for a in leer_gris(origen, aw, ah):
        f = a.astype(np.float32)
        F = _espectro(f, win)
        if ref is None:
            ref = F
        else:
            dx, dy, _ = _desplazamiento(F, ref, ah, aw, escala)
            absol.append(math.hypot(dx, dy))
        if prev is not None:
            dx, dy, _ = _desplazamiento(F, prev, ah, aw, escala)
            consec.append(math.hypot(dx, dy))
        if radio:
            s = _semilla_brillo(f)
            if s:
                cx, cy, k = ajustar_disco(f, s[0], s[1], radio / escala)
                if k >= 60:
                    descentr.append(math.hypot(cx - aw / 2, cy - ah / 2) * escala)
        prev = F
        n += 1
        if progress_cb and n % 25 == 0:
            progress_cb(min(1.0, n / max(1, info["frames"])))

    def resumen(v):
        if not v:
            return None
        v = np.array(v)
        return {"mediana": round(float(np.median(v)), 2),
                "p95": round(float(np.percentile(v, 95)), 2),
                "max": round(float(v.max()), 2)}

    return {"fotogramas": n, "temblor_consecutivo": resumen(consec),
            "desvio_vs_primero": resumen(absol),
            "descentrado_objeto": resumen(descentr)}
