"""Buscador de lugares y geocodificación inversa contra Nominatim (OpenStreetMap).

Se hace desde el servidor y no desde el navegador por dos motivos: para poder enviar el
User-Agent identificable que exige la política de uso de Nominatim, y para respetar el
límite de una petición por segundo sin depender de lo rápido que teclee quien busca.
"""

import json
import ssl
import threading
import time
import urllib.parse
import urllib.request

NOMINATIM = "https://nominatim.openstreetmap.org"
USER_AGENT = "ConversorVideo-Importador/1.0 (aplicación local de organización de fotos)"

_MIN_INTERVAL = 1.0
_last_call = 0.0
_lock = threading.Lock()


class PlacesError(RuntimeError):
    pass


def _ssl_context() -> ssl.SSLContext:
    """En macOS, el Python de Homebrew no lee el almacén de certificados del sistema, así
    que `urllib` falla con CERTIFICATE_VERIFY_FAILED contra cualquier HTTPS. `certifi`
    trae su propio paquete de raíces y viene instalado con `requests`."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _throttled_get(path: str, params: dict) -> list | dict:
    global _last_call
    url = f"{NOMINATIM}/{path}?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        # La política de uso de Nominatim exige un User-Agent que identifique la
        # aplicación; sin él bloquean las peticiones.
        "User-Agent": USER_AGENT,
        "Accept-Language": "es",
    })

    with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(request, timeout=20, context=_ssl_context()) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise PlacesError(
                f"No se pudo consultar OpenStreetMap: {exc}. "
                "El buscador de lugares necesita conexión a internet."
            ) from exc
        finally:
            _last_call = time.monotonic()

    return payload


def search(query: str, limit: int = 6) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    results = _throttled_get("search", {
        "q": query, "format": "jsonv2", "limit": str(limit), "addressdetails": "0",
    })
    return [
        {
            "name": item.get("display_name", ""),
            "gps": [float(item["lat"]), float(item["lon"])],
            "kind": item.get("type", ""),
        }
        for item in results
        if item.get("lat") and item.get("lon")
    ]


def reverse(lat: float, lon: float) -> str:
    """Nombre legible de unas coordenadas, para etiquetar un grupo ya localizado."""
    try:
        payload = _throttled_get("reverse", {
            "lat": str(lat), "lon": str(lon), "format": "jsonv2", "zoom": "14",
        })
    except PlacesError:
        return ""
    return payload.get("display_name", "") if isinstance(payload, dict) else ""
