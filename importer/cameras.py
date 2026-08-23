"""Traducción de modelo EXIF a nombre de carpeta ('ILCE-6400' -> 'Sony A6400').

El mapeo aprendido por el usuario vive en la configuración; esta tabla solo cubre los
modelos más habituales para que la primera importación ya proponga un nombre razonable.
Cuando el modelo no se reconoce, `suggest_folder()` compone uno legible y la interfaz
pide confirmarlo una vez; a partir de ahí queda memorizado.
"""

import re
import unicodedata

KNOWN_MODELS = {
    # Sony (Alpha / videocámaras / compactas)
    "ILCE-6000": "Sony A6000",
    "ILCE-6100": "Sony A6100",
    "ILCE-6400": "Sony A6400",
    "ILCE-6600": "Sony A6600",
    "ILCE-6700": "Sony A6700",
    "ILCE-7M3": "Sony A7 III",
    "ILCE-7M4": "Sony A7 IV",
    "ILCE-7RM4": "Sony A7R IV",
    "ILCE-7CM2": "Sony A7C II",
    "NEX-6": "Sony NEX-6",
    "DSC-RX100M5": "Sony RX100 V",
    "DSC-RX100M7": "Sony RX100 VII",
    "HDR-CX405": "Sony HDR-CX405",
    "HDR-CX625": "Sony HDR-CX625",
    "FDR-AX53": "Sony FDR-AX53",
    # Canon
    "Canon PowerShot G5 X": "Canon G5X",
    "Canon PowerShot G5 X Mark II": "Canon G5X Mark II",
    "Canon PowerShot G7 X Mark II": "Canon G7X Mark II",
    "Canon PowerShot G7 X Mark III": "Canon G7X Mark III",
    "Canon EOS R6": "Canon EOS R6",
    "Canon EOS R7": "Canon EOS R7",
    "Canon EOS 90D": "Canon EOS 90D",
    "Canon EOS 250D": "Canon EOS 250D",
    # Samsung (móviles). Ojo: **el mismo móvil se identifica de dos formas distintas**.
    # Las fotos llevan el nombre comercial en EXIF ("Galaxy S25 Ultra") y los vídeos el
    # código interno en un tag propio ("SM-S938B"). Ambos tienen que apuntar al mismo
    # nombre de carpeta o las fotos y los vídeos de una misma tarde acabarían separados.
    "SM-S918B": "Samsung S23 Ultra",
    "Galaxy S23 Ultra": "Samsung S23 Ultra",
    "SM-S928B": "Samsung S24 Ultra",
    "Galaxy S24 Ultra": "Samsung S24 Ultra",
    "SM-S938B": "Samsung S25 Ultra",
    "Galaxy S25 Ultra": "Samsung S25 Ultra",
    "SM-S931B": "Samsung S25",
    "Galaxy S25": "Samsung S25",
    "SM-S936B": "Samsung S25 Plus",
    "Galaxy S25+": "Samsung S25 Plus",
    # Apple
    "iPhone 14 Pro": "iPhone 14 Pro",
    "iPhone 15 Pro": "iPhone 15 Pro",
    "iPhone 16 Pro": "iPhone 16 Pro",
    # Acción / drones
    "HERO11 Black": "GoPro Hero 11",
    "HERO12 Black": "GoPro Hero 12",
    "FC3582": "DJI Mini 3 Pro",
}

# Pistas por estructura de la tarjeta, para cuando ningún fichero trae modelo en EXIF
# (típico de algunos .MTS de videocámara). Se usan solo como sugerencia.
STRUCTURE_HINTS = [
    ("CANONMSC", "Canon"),
    ("MSDCF", "Sony"),
    ("M4ROOT", "Sony"),
    ("PRIVATE/AVCHD", "Videocámara AVCHD"),
    ("AVCHD/BDMV", "Videocámara AVCHD"),
    ("APPLE", "iPhone"),
    ("DCIM/CAMERA", "Móvil Android"),
    ("DCIM/OPENCAMERA", "Móvil Android"),
]

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

UNKNOWN_FOLDER = "Sin identificar"


def sanitize_folder_name(name: str) -> str:
    """Nombre válido tanto en macOS como en Windows (que es más restrictivo).

    Devuelve cadena vacía si no queda nada aprovechable; decidir el nombre por defecto
    es cosa de quien llama, porque no es el mismo para una cámara que para un evento.
    """
    cleaned = unicodedata.normalize("NFC", name).strip()
    cleaned = _INVALID_CHARS.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:80]


def suggest_folder(make: str, model: str) -> str:
    """Nombre de carpeta propuesto para un modelo que aún no está en el mapeo."""
    model = (model or "").strip()
    make = (make or "").strip()
    if not model:
        return sanitize_folder_name(make) or UNKNOWN_FOLDER

    if model in KNOWN_MODELS:
        return KNOWN_MODELS[model]

    # El fabricante suele venir como "SONY"/"Canon Inc." y a menudo ya está dentro del
    # modelo ("Canon PowerShot G5 X"), así que solo se antepone si falta.
    brand = re.sub(r"\b(inc|corporation|corp|co|ltd)\b\.?", "", make, flags=re.I).strip()
    # Los fabricantes escriben la marca como les parece ("SONY", "samsung", "Canon"): se
    # normaliza para que no acabe una carpeta en minúscula al lado de otra en mayúscula.
    if brand.isupper() or brand.islower():
        brand = brand.title()
    if brand and not model.lower().startswith(brand.lower()):
        return sanitize_folder_name(f"{brand} {model}") or UNKNOWN_FOLDER
    return sanitize_folder_name(model) or UNKNOWN_FOLDER


def resolve_folder(make: str, model: str, mapping: dict) -> str:
    """Nombre definitivo: primero lo que el usuario ya decidió, si no una sugerencia."""
    if model and model in mapping:
        return sanitize_folder_name(mapping[model]) or UNKNOWN_FOLDER
    return suggest_folder(make, model)


def hint_from_structure(relative_paths: list[str]) -> str | None:
    upper = [p.upper().replace("\\", "/") for p in relative_paths[:200]]
    for needle, label in STRUCTURE_HINTS:
        if any(needle in path for path in upper):
            return label
    return None
