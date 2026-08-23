"""Detección de móviles conectados por USB (Android e iPhone).

**Por qué no aparecen en el Finder ni como una tarjeta más**: un móvil no se conecta como
disco USB. Usa MTP (Android) o PTP (iPhone y Android en «modo cámara»), que no son
sistemas de ficheros montables sino protocolos de petición de ficheros. macOS no lleva
soporte MTP en el Finder, así que no hay ninguna ruta que abrir — por eso el módulo no
puede tratarlos como un origen normal.

Lo que sí se puede hacer sin dependencias es **detectar que están enchufados** y guiar
hacia la forma que sí funciona: volcar con la app del sistema a una carpeta, que el
importador ya trata igual que una tarjeta.

Leer los ficheros directamente exigiría `libgphoto2` en macOS/Linux y WPD en Windows, con
el añadido de que en macOS `ptpcamerad` reclama el dispositivo en exclusiva y hay que
apartarlo antes. Ver DESARROLLO.md.
"""

import platform
import plistlib
import subprocess

# Fabricantes cuyos dispositivos interesan como origen de fotos, por ID de fabricante USB.
_VENDORS = {
    0x05AC: "Apple",
    0x04E8: "Samsung",
    0x18D1: "Google",
    0x2717: "Xiaomi",
    0x22B8: "Motorola",
    0x0BB4: "HTC",
    0x12D1: "Huawei",
    0x2A70: "OnePlus",
    0x0FCE: "Sony",
    0x1004: "LG",
}

# Los Mac llevan estos chips de Apple por dentro; sin filtrarlos, el teclado y el trackpad
# de un portátil aparecerían como "móviles Apple conectados".
_APPLE_INTERNAL = {"Apple Internal Keyboard", "Apple T2 Controller", "Headset",
                   "Ambient Light Sensor", "Touch Bar", "Apple Internal Trackpad"}


def _friendly(vendor: str, name: str) -> str:
    """Los móviles se anuncian con nombres genéricos (`SAMSUNG_Android`); se limpia para
    que en pantalla se lea como algo reconocible."""
    cleaned = (name or "").replace("_", " ").strip()
    if not cleaned or cleaned.lower() in ("android", f"{vendor.lower()} android"):
        return f"Móvil {vendor}"
    if vendor.lower() in cleaned.lower():
        return cleaned
    return f"{vendor} {cleaned}"


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.get("IORegistryEntryChildren", []))


def _macos_phones() -> list[dict]:
    result = subprocess.run(
        ["ioreg", "-p", "IOUSB", "-a", "-l", "-w0"], capture_output=True, timeout=20
    )
    if result.returncode != 0 or not result.stdout:
        return []
    try:
        tree = plistlib.loads(result.stdout)
    except Exception:
        return []
    if isinstance(tree, dict):
        tree = [tree]

    phones = []
    for node in _walk(tree):
        vendor_id = node.get("idVendor")
        if vendor_id not in _VENDORS:
            continue
        raw_name = node.get("USB Product Name") or node.get("kUSBProductString") or ""
        if raw_name in _APPLE_INTERNAL:
            continue
        vendor = _VENDORS[vendor_id]
        # De Apple solo interesan iPhone y iPad, no el resto de periféricos de la casa.
        if vendor == "Apple" and not any(k in raw_name for k in ("iPhone", "iPad", "iPod")):
            continue
        phones.append({
            "label": _friendly(vendor, raw_name),
            "vendor": vendor,
            "serial": node.get("USB Serial Number") or "",
            "kind": "iphone" if vendor == "Apple" else "android",
        })
    return phones


def _windows_phones() -> list[dict]:
    """En Windows los móviles sí aparecen como «dispositivos portátiles» (WPD), y con una
    letra de unidad accesible en algunos casos. Aquí solo se listan por nombre."""
    script = (
        "Get-PnpDevice -Class WPD -Status OK | "
        "Select-Object -ExpandProperty FriendlyName"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [
        {"label": line.strip(), "vendor": "", "serial": "",
         "kind": "iphone" if "iphone" in line.lower() else "android"}
        for line in result.stdout.splitlines() if line.strip()
    ]


def detect_phones() -> list[dict]:
    """Móviles enchufados ahora mismo. Nunca lanza: si falla, es que no hay ninguno."""
    try:
        if platform.system() == "Darwin":
            return _macos_phones()
        if platform.system() == "Windows":
            return _windows_phones()
    except Exception:
        return []
    return []


def open_transfer_app(kind: str = "android") -> tuple[bool, str]:
    """Abre la aplicación del sistema que sí sabe hablar con el móvil.

    En macOS, Captura de Imagen puede volcar a una carpeta cualquiera, y esa carpeta la
    detecta este mismo importador como si fuera una tarjeta.
    """
    if platform.system() != "Darwin":
        return False, "Solo disponible en macOS."
    result = subprocess.run(["open", "-a", "Image Capture"], capture_output=True, text=True)
    if result.returncode != 0:
        return False, "No se pudo abrir Captura de Imagen."
    return True, "Captura de Imagen abierta."
