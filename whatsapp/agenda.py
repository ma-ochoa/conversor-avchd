"""Agenda de contactos importada de fuera, para poner nombres a los números.

**Por qué hace falta.** WhatsApp no guarda los nombres en ninguna parte que se pueda
copiar. Comprobado sobre un Galaxy S25 real: la tabla `wa_contacts` de `wa.db` existe con
todas sus columnas y tiene **cero filas**, y de las 903 de `lid_display_name` solo dos no
son un número de teléfono. Los nombres los lee WhatsApp de la agenda del sistema cada vez
que los enseña, y esa agenda vive en el almacenamiento privado del proveedor de contactos
de Android — la misma pared que la base de mensajes.

**Tampoco sale por MTP.** MTP expone el almacenamiento compartido; la agenda no está ahí.
Lo que sí funciona es exportarla a un `.vcf` desde el propio móvil (la app de Contactos
sabe hacerlo) y dejar el fichero en la memoria interna, que entonces sí se lee por USB.

Así que la agenda entra **desde un fichero**, y se admiten los dos formatos en que la
exporta todo el mundo:

  · **vCard (.vcf)** — Google Contactos, iCloud, la app Contactos de macOS, la app de
    Contactos del móvil, y la copia de seguridad de un iPhone.
  · **CSV de Google Contactos** — el que sale de contacts.google.com.

En un Mac, la vía más corta es la app **Contactos**: ya tiene unificadas las cuentas de
Google y de iCloud, y exporta un único `.vcf` con todo (Archivo → Exportar → Exportar
vCard). Un solo fichero, las dos cuentas, sin pasar por el navegador.

**Lo difícil no es leer el fichero, es casar los números.** En una agenda están escritos
como `655 12 34 56`, `+34 655 123 456` o `0034655123456`, y WhatsApp los identifica como
`34655123456@s.whatsapp.net`. Se normaliza todo a dígitos y se indexa además por los
últimos `SUFIJO` dígitos, que es lo que permite casar un número guardado sin prefijo con
uno de WhatsApp que sí lo lleva.
"""

import csv
import json
import quopri
import re
import threading
from pathlib import Path

from .config import DIR_DATOS

AGENDA_IMPORTADA = DIR_DATOS / "agenda.json"

# Cuántos dígitos finales se usan para casar cuando el número no coincide entero. Nueve
# es la longitud de un número español sin prefijo; con menos empezarían los falsos
# positivos entre gente distinta.
SUFIJO = 9

_lock = threading.Lock()


# --------------------------------------------------------------------- números

def normaliza(numero: str) -> str:
    """Deja solo dígitos y quita el prefijo internacional escrito como `00`."""
    digitos = re.sub(r"\D", "", numero or "")
    if digitos.startswith("00"):
        digitos = digitos[2:]
    return digitos


def _claves(numero: str) -> list[str]:
    """Con qué llaves se indexa un número: el entero y su sufijo."""
    d = normaliza(numero)
    if not d:
        return []
    llaves = [d]
    if len(d) > SUFIJO:
        llaves.append(d[-SUFIJO:])
    return llaves


# --------------------------------------------------------------------- vCard

# Las líneas de una vCard se parten a los 75 caracteres y continúan con un espacio o
# tabulador al principio. Sin deshacer ese plegado, un nombre largo llega cortado.
def _despliega(texto: str) -> list[str]:
    lineas = []
    for cruda in texto.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if cruda[:1] in (" ", "\t") and lineas:
            lineas[-1] += cruda[1:]
        else:
            lineas.append(cruda)
    return lineas


def _valor(linea: str) -> tuple[str, dict, str]:
    """Parte `FN;CHARSET=UTF-8:Pepe` en (propiedad, parámetros, valor)."""
    nombre, _, valor = linea.partition(":")
    trozos = nombre.split(";")
    props = {}
    for t in trozos[1:]:
        k, _, v = t.partition("=")
        props[k.upper()] = v.upper()
    return trozos[0].upper(), props, valor


def _descodifica(valor: str, params: dict) -> str:
    """Las vCard 2.1 de muchos móviles vienen en quoted-printable, y sin descodificarlo
    los acentos salen como `=C3=A9`."""
    if params.get("ENCODING") in ("QUOTED-PRINTABLE", "Q"):
        try:
            return quopri.decodestring(valor.encode("utf-8")).decode(
                "utf-8" if params.get("CHARSET", "UTF-8") == "UTF-8" else "latin-1",
                errors="replace")
        except Exception:
            return valor
    return valor


def lee_vcard(ruta: Path) -> list[dict]:
    """[{'nombre', 'numeros': [...]}] a partir de un .vcf."""
    texto = Path(ruta).read_text(encoding="utf-8", errors="replace")
    contactos, actual = [], None

    for linea in _despliega(texto):
        if not linea.strip():
            continue
        prop, params, valor = _valor(linea)

        if prop == "BEGIN" and valor.upper() == "VCARD":
            actual = {"nombre": "", "apellidos": "", "numeros": []}
        elif prop == "END" and valor.upper() == "VCARD":
            if actual and actual["numeros"]:
                contactos.append({
                    "nombre": actual["nombre"] or actual["apellidos"] or "",
                    "numeros": actual["numeros"],
                })
            actual = None
        elif actual is None:
            continue
        elif prop == "FN":
            actual["nombre"] = _descodifica(valor, params).strip()
        elif prop == "N" and not actual["apellidos"]:
            # `N` viene como Apellidos;Nombre;...  — se recompone al derecho.
            partes = [p.strip() for p in _descodifica(valor, params).split(";")]
            apellido, nombre = (partes + ["", ""])[:2]
            actual["apellidos"] = " ".join(x for x in (nombre, apellido) if x)
        elif prop == "TEL":
            numero = _descodifica(valor, params).strip()
            if normaliza(numero):
                actual["numeros"].append(numero)

    return contactos


# ----------------------------------------------------------------------- CSV

# Columnas que ya traen el nombre entero. Las tienen los formatos antiguos de Google y
# los de otros sitios; **el CSV que exporta hoy Google Contactos no trae ninguna**: el
# nombre viene siempre partido, y darlo por perdido dejaba la agenda casi vacía.
_COL_NOMBRE = ("name", "display name", "full name", "nombre para mostrar")

# Con qué columnas se arma el nombre cuando viene partido, que es el caso normal hoy.
# Dentro de cada grupo se coge la primera que traiga algo.
_COL_PARTES = (
    ("first name", "given name", "nombre"),
    ("middle name", "additional name", "segundo nombre"),
    ("last name", "family name", "apellidos", "apellido"),
)

# Cuando no hay nombre de persona. Una agenda está llena de comercios y servicios
# —talleres, médicos, restaurantes— que solo tienen razón social.
_COL_RESPALDO = ("file as", "organization name", "organization", "company", "nickname",
                 "empresa", "organización", "organizacion")

_COL_TEL = ("phone", "teléfono", "telefono", "mobile", "móvil", "movil")

# `Phone 1 - Label` trae «Mobile» o «Casa», no un número.
_FIN_ETIQUETA = ("label", "type", "etiqueta", "tipo")

# `Phonetic First Name` contiene «phone» sin tener nada que ver con un teléfono.
_NO_ES_TEL = ("phonetic", "fonetic", "fonétic")


def _fila_limpia(fila: dict) -> dict[str, str]:
    """La fila con los nombres de columna en minúsculas y sin espacios sobrantes."""
    limpia = {}
    for columna, valor in fila.items():
        # Una fila con más campos que la cabecera se lo lleva todo a la clave None, y
        # como lista. Se descarta esa fila torcida en vez de reventar la importación.
        if columna is None or isinstance(valor, list):
            continue
        limpia[columna.strip().lower()] = (valor or "").strip()
    return limpia


def _nombre_de(fila: dict[str, str]) -> str:
    """El nombre del contacto, venga como venga en el CSV.

    Se prueba primero una columna con el nombre entero; si no la hay, se arma con las
    partes; y si tampoco —los comercios no tienen nombre de pila— se tira de la
    organización.
    """
    for columna in _COL_NOMBRE:
        if fila.get(columna):
            return fila[columna]

    partes = []
    for alternativas in _COL_PARTES:
        for columna in alternativas:
            if fila.get(columna):
                partes.append(fila[columna])
                break
    if partes:
        return " ".join(partes)

    for columna in _COL_RESPALDO:
        if fila.get(columna):
            return fila[columna]
    return ""


def _es_columna_telefono(columna: str) -> bool:
    if any(x in columna for x in _NO_ES_TEL):
        return False
    if not any(x in columna for x in _COL_TEL):
        return False
    return columna.rsplit("-", 1)[-1].strip() not in _FIN_ETIQUETA


def lee_csv(ruta: Path) -> list[dict]:
    """El CSV de Google Contactos: una fila por contacto y varias columnas de teléfono."""
    with open(ruta, newline="", encoding="utf-8-sig", errors="replace") as f:
        muestra = f.read(4096)
        f.seek(0)
        try:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t")
        except csv.Error:
            dialecto = csv.excel
        filas = list(csv.DictReader(f, dialect=dialecto))

    contactos = []
    for cruda in filas:
        fila = _fila_limpia(cruda)
        numeros = []
        for columna, valor in fila.items():
            if valor and _es_columna_telefono(columna):
                # Google separa varios números de una misma celda con ' ::: '.
                numeros += [n.strip() for n in re.split(r":::|\s*/\s*", valor)
                            if normaliza(n)]
        if numeros:
            contactos.append({"nombre": _nombre_de(fila), "numeros": numeros})
    return contactos


# ------------------------------------------------------------------- almacén

def importa(ruta: str | Path) -> dict:
    """Lee un .vcf o un .csv y lo guarda como agenda. Devuelve un resumen.

    Sustituye la agenda anterior en vez de fusionarla: mezclar dos exportaciones sin
    saber cuál es más reciente produciría nombres viejos ganando a los nuevos sin que
    nadie pueda explicar por qué.
    """
    ruta = Path(ruta).expanduser()
    if not ruta.is_file():
        raise FileNotFoundError(f"No existe: {ruta}")

    sufijo = ruta.suffix.lower()
    if sufijo in (".vcf", ".vcard"):
        contactos = lee_vcard(ruta)
    elif sufijo in (".csv", ".tsv", ".txt"):
        contactos = lee_csv(ruta)
    else:
        raise ValueError(
            f"No sé leer «{ruta.suffix}». Exporta la agenda como vCard (.vcf) o como "
            f"CSV de Google Contactos."
        )

    indice: dict[str, str] = {}
    con_nombre = 0
    for c in contactos:
        nombre = (c["nombre"] or "").strip()
        if not nombre:
            continue
        con_nombre += 1
        for numero in c["numeros"]:
            for llave in _claves(numero):
                # El primero gana: una agenda suele traer el nombre bueno antes que los
                # duplicados de sincronización.
                indice.setdefault(llave, nombre)

    with _lock:
        DIR_DATOS.mkdir(parents=True, exist_ok=True)
        AGENDA_IMPORTADA.write_text(json.dumps({
            "origen": str(ruta),
            "formato": "vcard" if sufijo in (".vcf", ".vcard") else "csv",
            "contactos": con_nombre,
            "numeros": len(indice),
            "indice": indice,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    return {"origen": str(ruta), "contactos_leidos": len(contactos),
            "contactos_con_nombre": con_nombre, "numeros_indexados": len(indice)}


def cargada() -> dict:
    """La agenda guardada, o un hueco vacío si no hay ninguna."""
    if not AGENDA_IMPORTADA.is_file():
        return {"contactos": 0, "numeros": 0, "indice": {}, "origen": None}
    try:
        return json.loads(AGENDA_IMPORTADA.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"contactos": 0, "numeros": 0, "indice": {}, "origen": None}


def olvida() -> bool:
    with _lock:
        if AGENDA_IMPORTADA.is_file():
            AGENDA_IMPORTADA.unlink()
            return True
    return False


def busca(numero: str, indice: dict[str, str] | None = None) -> str | None:
    """Nombre de un número, probando el número entero y luego su sufijo."""
    indice = cargada()["indice"] if indice is None else indice
    for llave in _claves(numero):
        if llave in indice:
            return indice[llave]
    return None
