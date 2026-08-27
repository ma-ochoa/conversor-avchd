"""Envío de lo importado al NAS.

Sobre la API de Synology Photos: **no existe una API pública para terceros**. Las
llamadas `SYNO.Foto.*` que usa la app oficial solo están documentadas por ingeniería
inversa de la comunidad, sin contrato estable entre versiones de DSM, así que construir
sobre ellas rompería el envío en cualquier actualización del NAS.

Lo que sí es oficial y documentado por Synology es **File Station** (`SYNO.FileStation.*`).
Subir a la carpeta que Synology Photos ya tiene indexada (`/photo`, o
`/homes/<usuario>/Photos` en espacios personales — en plural en DSM 7) hace que Photos
indexe las fotos por su cuenta, que es exactamente el resultado buscado. Por eso ese es el método recomendado aquí, y va sobre HTTPS con la
cuenta de DSM (compatible con 2FA), sin necesidad de activar el servicio FTP en el NAS.

SFTP y FTP quedan como alternativas para NAS que no sean Synology o instalaciones donde
File Station no esté disponible.
"""

import ftplib
import platform
import posixpath
import ssl
import sys
import uuid
from pathlib import Path


def _como_instalar(paquete: str) -> str:
    """El comando que instala `paquete` **en el entorno que está ejecutando la app**.

    Se da la ruta del intérprete en vez de un `pip` a secas porque en macOS ese `pip`
    suele ser el de Homebrew, que rechaza instalar nada (PEP 668) y, aunque funcionara,
    lo instalaría en un entorno distinto del que después va a buscar el módulo.
    """
    return f"{sys.executable} -m pip install {paquete}"


def _device_name() -> str:
    """Nombre con el que este equipo aparece en la lista de dispositivos de confianza de
    DSM. Se usa el del sistema para que sea reconocible al revisarla o revocarlo."""
    return f"Conversor de vídeo ({platform.node() or 'equipo'})"

DEFAULT_PORTS = {"synology": 5001, "synology_http": 5000, "sftp": 22, "ftp": 21, "ftps": 21}


class NasError(RuntimeError):
    pass


class NasOtpRequired(NasError):
    """La cuenta tiene 2FA y hace falta un código *en este momento*.

    Se distingue del resto de errores porque la interfaz tiene que reaccionar pidiendo el
    código, no mostrando un fallo. Un código TOTP vale 30 segundos: no tiene sentido
    guardarlo en la configuración, hay que pedirlo cuando se va a usar.
    """


def _remote_path(remote_root: str, relative: str) -> str:
    return posixpath.join(remote_root.rstrip("/"), Path(relative).as_posix())


# ---------------------------------------------------------------- Synology File Station

# **Synology reutiliza los mismos números con significados distintos según la API.** El
# 407 es "IP bloqueada" en el login pero "operación no permitida" en File Station, y el
# 408 es "contraseña caducada" frente a "no existe esa carpeta". Con una sola tabla, un
# `/photo` inexistente se anunciaba como una contraseña caducada, y un permiso que falta
# como una IP bloqueada — mandando a mirar justo donde no estaba el problema.

_COMMON_ERRORS = {
    100: "Error desconocido en el NAS.",
    101: "Parámetro no válido en la petición.",
    102: "El NAS no reconoce esa función de su API.",
    103: "El NAS no reconoce ese método de su API.",
    104: "La versión de la API que pide esta app no está disponible en tu DSM.",
    105: "La sesión no tiene permiso para esta operación.",
    106: "La sesión ha caducado. Vuelve a probar la conexión.",
    107: "La sesión se interrumpió por un inicio de sesión duplicado.",
    119: "La sesión ya no es válida en el NAS.",
}

_AUTH_ERRORS = {
    400: "Usuario o contraseña incorrectos.",
    401: "La cuenta está deshabilitada en el NAS.",
    402: "La cuenta no tiene permisos suficientes.",
    403: "La cuenta tiene la verificación en dos pasos activada: hace falta el código.",
    404: "El código de verificación en dos pasos no es correcto.",
    406: "El NAS exige verificación en dos pasos para esta cuenta.",
    407: "El NAS ha bloqueado esta IP (Panel de control → Seguridad → Bloqueo automático).",
    408: "La contraseña ha caducado y hay que cambiarla en DSM.",
    409: "La contraseña ha caducado.",
    410: "Hay que cambiar la contraseña en DSM antes de poder entrar.",
}

_FILESTATION_ERRORS = {
    400: "Parámetro no válido en la operación de archivo.",
    401: "Error desconocido en la operación de archivo.",
    402: "El NAS está demasiado ocupado.",
    403: "Este usuario no puede hacer esa operación.",
    406: "No se pudo obtener la información de la cuenta desde el NAS.",
    407: "Operación no permitida: la cuenta no tiene permiso de escritura sobre esa carpeta.",
    408: "No existe esa carpeta en el NAS.",
    409: "Sistema de archivos no soportado.",
    410: "No se pudo conectar con el sistema de archivos remoto.",
    411: "La carpeta es de solo lectura.",
    414: "El nombre es demasiado largo.",
    415: "El sistema de archivos es de solo lectura.",
    1100: "No se pudo crear la carpeta.",
    1101: "Se superaría el límite de carpetas del sistema.",
}


def _error_text(code, api: str, context: str) -> str:
    if code in _COMMON_ERRORS:
        return _COMMON_ERRORS[code]
    table = _AUTH_ERRORS if api.startswith("SYNO.API.Auth") else _FILESTATION_ERRORS
    return table.get(code, f"{context}: el NAS devolvió el error {code}.")


def _syno_root(settings: dict) -> str:
    scheme = "https" if settings.get("use_https", True) else "http"
    port = settings.get("port") or (DEFAULT_PORTS["synology"] if scheme == "https" else DEFAULT_PORTS["synology_http"])
    return f"{scheme}://{settings['host']}:{port}/webapi"


def _syno_base(settings: dict) -> str:
    return f"{_syno_root(settings)}/entry.cgi"


# Versión máxima de cada API que este código sabe manejar. El NAS puede ofrecer versiones
# más nuevas, pero pedir una que no conocemos cambiaría el formato de la respuesta.
_KNOWN_MAX_VERSION = {
    "SYNO.API.Auth": 6,
    "SYNO.FileStation.List": 2,
    "SYNO.FileStation.CreateFolder": 2,
    "SYNO.FileStation.Upload": 2,
}

# Si `SYNO.API.Info` no responde, se usan estos valores: son los de DSM 7, el caso común.
_FALLBACK = {name: {"version": version, "path": "entry.cgi"}
             for name, version in _KNOWN_MAX_VERSION.items()}


# El NAS pide un código 2FA: no es un fallo, es un paso más del login.
_OTP_CODES = {403, 406}


def _syno_check(payload: dict, context: str, api: str = "SYNO.FileStation") -> dict:
    """`api` decide qué tabla de errores se usa: el mismo número significa cosas
    distintas en el login y en File Station."""
    if payload.get("success"):
        return payload.get("data", {})
    code = (payload.get("error") or {}).get("code")
    message = _error_text(code, api, context)
    # Solo el login pide un segundo factor; un 403 de File Station es otra cosa.
    if api.startswith("SYNO.API.Auth") and code in _OTP_CODES:
        raise NasOtpRequired(message)
    raise NasError(message)


def _redact(message: str, *secrets: str) -> str:
    """Los errores de red de `requests` incluyen la URL completa de la petición, y ese
    texto acaba en pantalla y en los logs. Sin esto, una credencial que viajara en la
    query se filtraría en el mensaje de error."""
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message


class _MultipartStream:
    """Cuerpo `multipart/form-data` que lee el fichero por trozos según se envía.

    **Por qué no vale `files=` de requests**: construye el cuerpo entero en memoria y lo
    vuelca al socket de una vez. Con las fotos (2-3 MB) no se nota, pero con un vídeo de
    100 MB o más la escritura se atasca y la conexión muere con
    `TimeoutError('The write operation timed out')` — pasaba con los 26 vídeos de una
    biblioteca real, mientras las 554 fotos habían subido sin problema.

    Leyendo por trozos, ese mismo vídeo de 119 MB sube en 53 s, y además va más rápido
    (2,2 MB/s frente a 1,2) porque no hay que serializarlo todo antes de empezar.
    """

    CHUNK = 1024 * 256

    def __init__(self, fields: list[tuple[str, str]], path: Path, filename: str):
        self.boundary = uuid.uuid4().hex
        frontier = self.boundary.encode()

        head = b""
        for name, value in fields:
            head += (b'--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                     % (frontier, name.encode(), str(value).encode()))
        # El binario va en la última parte: es un requisito de File Station.
        head += (b'--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\n'
                 b'Content-Type: application/octet-stream\r\n\r\n'
                 % (frontier, filename.encode()))

        self._head = head
        self._tail = b"\r\n--%s--\r\n" % frontier
        self._path = Path(path)
        self._size = self._path.stat().st_size
        self._handle = None
        self._sent_head = 0
        self._sent_tail = 0

    def __len__(self) -> int:
        return len(self._head) + self._size + len(self._tail)

    @property
    def content_type(self) -> str:
        return f"multipart/form-data; boundary={self.boundary}"

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            amount = self.CHUNK

        if self._sent_head < len(self._head):
            chunk = self._head[self._sent_head:self._sent_head + amount]
            self._sent_head += len(chunk)
            return chunk

        if self._handle is None:
            self._handle = open(self._path, "rb")
        chunk = self._handle.read(amount)
        if chunk:
            return chunk

        if self._sent_tail < len(self._tail):
            chunk = self._tail[self._sent_tail:self._sent_tail + amount]
            self._sent_tail += len(chunk)
            return chunk
        return b""

    def close(self) -> None:
        if self._handle:
            self._handle.close()
            self._handle = None


class _SynologySession:
    def __init__(self, settings: dict):
        try:
            import requests
        except ImportError as exc:
            raise NasError(
                "Falta la librería 'requests' para hablar con el NAS por File Station. "
                f"Instálala con: {_como_instalar('requests')}"
            ) from exc

        self.requests = requests
        self.settings = settings
        self.root = _syno_root(settings)
        self.url = _syno_base(settings)
        self.session = requests.Session()
        self.session.verify = bool(settings.get("verify_tls", True))
        self.sid = None
        self.device_id = None
        self._created_dirs: set[str] = set()
        self.apis = dict(_FALLBACK)

    def discover(self) -> None:
        """Pregunta al NAS qué versión de cada API soporta, antes de autenticarse.

        Cada DSM admite un rango distinto (`SYNO.API.Auth` es la versión 6 en DSM 7 y la 3
        en DSM 6), y pedir una fuera de rango no da un error claro: devuelve un código
        genérico que se confunde con credenciales incorrectas. `SYNO.API.Info` no necesita
        sesión, así que se consulta primero y se negocia la versión más alta que ambos
        lados entienden. Si la consulta falla se sigue con los valores de DSM 7, que es lo
        que había antes de negociar nada.
        """
        try:
            response = self.session.get(
                f"{self.root}/query.cgi",
                params={
                    "api": "SYNO.API.Info",
                    "version": "1",
                    "method": "query",
                    "query": ",".join(_KNOWN_MAX_VERSION),
                },
                timeout=(10, 30),
            )
            payload = response.json()
        except Exception:
            return

        if not payload.get("success"):
            return

        for name, info in (payload.get("data") or {}).items():
            if name not in _KNOWN_MAX_VERSION:
                continue
            try:
                lowest = int(info.get("minVersion", 1))
                highest = int(info.get("maxVersion", 1))
            except (TypeError, ValueError):
                continue
            # La más alta que soportan los dos; si el NAS es tan antiguo que ni su máxima
            # llega a nuestra mínima, se usa la suya y que falle con su propio mensaje.
            chosen = min(highest, _KNOWN_MAX_VERSION[name])
            self.apis[name] = {
                "version": max(chosen, lowest) if chosen < lowest else chosen,
                # En DSM 6 el login vive en `auth.cgi`, no en `entry.cgi`.
                "path": info.get("path") or "entry.cgi",
            }

    def api_version(self, name: str) -> str:
        return str(self.apis.get(name, _FALLBACK[name])["version"])

    def api_url(self, name: str) -> str:
        return f"{self.root}/{self.apis.get(name, _FALLBACK[name])['path']}"

    def post(self, data: dict, **kwargs):
        """Todas las llamadas van por POST con los parámetros en el cuerpo: en la query
        acabarían en el registro de accesos del NAS, credenciales incluidas."""
        # Cada API puede vivir en un .cgi distinto según la versión de DSM.
        url = self.api_url(data["api"]) if isinstance(data, dict) and "api" in data else self.url
        try:
            return self.session.post(url, data=data, timeout=(10, 120), **kwargs)
        except self.requests.exceptions.SSLError as exc:
            raise NasError(
                "Error de certificado TLS. Si el NAS usa un certificado autofirmado, "
                "desactiva «Verificar certificado» en la configuración."
            ) from exc
        except self.requests.exceptions.RequestException as exc:
            detail = _redact(str(exc), self.settings.get("password", ""), self.settings.get("otp", ""))
            raise NasError(f"No se pudo conectar con {self.settings['host']}: {detail}") from exc

    def __enter__(self):
        self.discover()
        self.login()
        return self

    def relogin(self) -> None:
        """Rehace la sesión. El token de dispositivo evita volver a pedir el código 2FA,
        que en mitad de una subida en segundo plano no habría a quién pedírselo."""
        self.sid = None
        self.login()

    def login(self) -> None:
        data = {
            "api": "SYNO.API.Auth",
            "version": self.api_version("SYNO.API.Auth"),
            "method": "login",
            "account": self.settings["user"],
            "passwd": self.settings["password"],
            "session": "FileStation",
            "format": "sid",
        }

        otp = (self.settings.get("otp") or "").strip()
        device_id = (self.settings.get("device_id") or "").strip()

        if otp:
            # Con un código válido se pide además que el NAS "confíe" en este equipo: la
            # respuesta trae un `did` que en los siguientes logins sustituye al código.
            # Es el mismo mecanismo que la casilla "recordar este dispositivo" de DSM.
            data["otp_code"] = otp
            data["enable_device_token"] = "yes"
            data["device_name"] = self.settings.get("device_name") or _device_name()
        elif device_id:
            # Con el token guardado, el NAS no vuelve a pedir el segundo factor.
            data["device_id"] = device_id

        result = _syno_check(self.post(data).json(), "Inicio de sesión", "SYNO.API.Auth")
        self.sid = result["sid"]
        # Solo viene cuando se ha pedido enable_device_token, o sea en el login con código.
        self.device_id = result.get("did") or device_id
        # Algunas rutas de DSM identifican la sesión por cookie en vez de por el `_sid`
        # del cuerpo; ponerla es gratis y cubre ese caso.
        self.session.cookies.set("id", self.sid)

    def __exit__(self, *_exc):
        if self.sid:
            try:
                self.post({"api": "SYNO.API.Auth",
                           "version": self.api_version("SYNO.API.Auth"),
                           "method": "logout",
                           "session": "FileStation", "_sid": self.sid})
            except NasError:
                pass
        self.session.close()

    def ensure_dir(self, remote_dir: str) -> None:
        """Intenta crear la carpeta remota, **sin que su fallo sea fatal**.

        Crear una carpeta que ya existe devuelve `400` («parámetro no válido»), no un
        código de "ya existe" — así que enumerar códigos no vale: en la segunda pasada
        sobre las mismas carpetas, un error legítimo y uno inofensivo son el mismo número.
        Y abortar ahí rompía justo la reanudación de una subida a medias, que es cuando
        las carpetas ya están todas creadas.

        No hace falta ser estricto: la propia subida va con `create_parents=true` y crea
        lo que falte. Esto es solo un adelanto para que el árbol aparezca ordenado.
        """
        if remote_dir in self._created_dirs:
            return
        parent, _, name = remote_dir.rstrip("/").rpartition("/")
        try:
            self.post({
                "api": "SYNO.FileStation.CreateFolder",
                "version": self.api_version("SYNO.FileStation.CreateFolder"),
                "method": "create", "folder_path": parent or "/", "name": name,
                "force_parent": "true", "_sid": self.sid,
            })
        except NasError:
            pass
        self._created_dirs.add(remote_dir)

    def upload(self, local: Path, remote_dir: str, filename: str, _retry: bool = True) -> None:
        self.ensure_dir(remote_dir)

        body = _MultipartStream(
            [
                ("api", "SYNO.FileStation.Upload"),
                ("version", self.api_version("SYNO.FileStation.Upload")),
                ("method", "upload"),
                ("_sid", self.sid),
                ("path", remote_dir),
                ("create_parents", "true"),
                ("overwrite", "skip"),
            ],
            local, filename,
        )
        try:
            response = self.session.post(
                self.api_url("SYNO.FileStation.Upload"),
                # **El `_sid` va además en la query.** En una petición multipart DSM
                # no lo lee de forma fiable del cuerpo y responde 119 («sesión no
                # válida») aunque el login acabe de funcionar y `ensure_dir` —que va
                # por POST normal— haya ido bien un instante antes.
                params={"_sid": self.sid},
                data=body,
                headers={"Content-Type": body.content_type,
                         "Content-Length": str(len(body))},
                # Generoso pero finito: un vídeo grande tarda minutos, y `None` no vale
                # porque deja el connect timeout aplicado a la escritura y corta a los 10 s.
                timeout=(15, 600),
            )
        except self.requests.exceptions.RequestException as exc:
            detail = _redact(str(exc), self.settings.get("password", ""))
            raise NasError(f"Error subiendo {filename}: {detail}") from exc
        finally:
            body.close()

        payload = response.json()
        code = (payload.get("error") or {}).get("code")
        # Una subida larga puede agotar la sesión por el camino: se rehace una vez y se
        # reintenta, en vez de dar por perdido todo lo que quedaba.
        if not payload.get("success") and code in (105, 106, 119) and _retry:
            self.relogin()
            return self.upload(local, remote_dir, filename, _retry=False)

        _syno_check(payload, f"Subir {filename}", "SYNO.FileStation.Upload")


def _upload_synology(files: list[tuple[Path, str]], settings: dict, progress_cb) -> None:
    remote_root = settings.get("remote_root", "/photo")
    with _SynologySession(settings) as session:
        for index, (local, relative) in enumerate(files, start=1):
            remote = _remote_path(remote_root, relative)
            session.upload(local, posixpath.dirname(remote), posixpath.basename(remote))
            if progress_cb:
                progress_cb(index, relative)


# ------------------------------------------------------------------------------- SFTP

def _upload_sftp(files: list[tuple[Path, str]], settings: dict, progress_cb) -> None:
    try:
        import paramiko
    except ImportError as exc:
        raise NasError(
            "Falta la librería 'paramiko' para subir por SFTP. Instálala con: "
            f"{_como_instalar('paramiko')}"
        ) from exc

    port = settings.get("port") or DEFAULT_PORTS["sftp"]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(settings["host"], port=port, username=settings["user"],
                       password=settings["password"], timeout=30)
    except Exception as exc:
        raise NasError(f"No se pudo conectar por SFTP a {settings['host']}: {_redact(str(exc), settings.get('password', ''))}") from exc

    try:
        sftp = client.open_sftp()
        made: set[str] = set()
        remote_root = settings.get("remote_root", "/photo")
        for index, (local, relative) in enumerate(files, start=1):
            remote = _remote_path(remote_root, relative)
            _sftp_makedirs(sftp, posixpath.dirname(remote), made)
            sftp.put(str(local), remote)
            if progress_cb:
                progress_cb(index, relative)
        sftp.close()
    finally:
        client.close()


def _sftp_makedirs(sftp, remote_dir: str, made: set[str]) -> None:
    if remote_dir in made or remote_dir in ("/", ""):
        return
    _sftp_makedirs(sftp, posixpath.dirname(remote_dir), made)
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        sftp.mkdir(remote_dir)
    made.add(remote_dir)


# -------------------------------------------------------------------------- FTP / FTPS

def _ftp_connect(settings: dict):
    port = settings.get("port") or DEFAULT_PORTS["ftp"]
    if settings["method"] == "ftps":
        context = ssl.create_default_context()
        if not settings.get("verify_tls", True):
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        ftp = ftplib.FTP_TLS(context=context)
    else:
        ftp = ftplib.FTP()

    ftp.connect(settings["host"], port, timeout=30)
    ftp.login(settings["user"], settings["password"])
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()
    ftp.set_pasv(True)
    return ftp


def _upload_ftp(files: list[tuple[Path, str]], settings: dict, progress_cb) -> None:
    try:
        ftp = _ftp_connect(settings)
    except ftplib.all_errors as exc:
        raise NasError(f"No se pudo conectar por FTP a {settings['host']}: {_redact(str(exc), settings.get('password', ''))}") from exc

    try:
        made: set[str] = set()
        remote_root = settings.get("remote_root", "/photo")
        for index, (local, relative) in enumerate(files, start=1):
            remote = _remote_path(remote_root, relative)
            _ftp_makedirs(ftp, posixpath.dirname(remote), made)
            with open(local, "rb") as handle:
                ftp.storbinary(f"STOR {remote}", handle, blocksize=1024 * 1024)
            if progress_cb:
                progress_cb(index, relative)
    finally:
        try:
            ftp.quit()
        except ftplib.all_errors:
            ftp.close()


def _ftp_makedirs(ftp, remote_dir: str, made: set[str]) -> None:
    if remote_dir in made or remote_dir in ("/", ""):
        return
    _ftp_makedirs(ftp, posixpath.dirname(remote_dir), made)
    try:
        ftp.mkd(remote_dir)
    except ftplib.error_perm:
        pass  # Ya existe: es el caso normal a partir de la segunda importación.
    made.add(remote_dir)


# ----------------------------------------------------------------------------- Público

_BACKENDS = {
    "synology": _upload_synology,
    "sftp": _upload_sftp,
    "ftp": _upload_ftp,
    "ftps": _upload_ftp,
}


def upload_files(files: list[tuple[Path, str]], settings: dict, progress_cb=None) -> None:
    """Sube [(ruta local, ruta relativa al destino)] replicando la estructura en el NAS."""
    if not settings.get("host") or not settings.get("user"):
        raise NasError("Faltan los datos de conexión del NAS (servidor y usuario).")

    backend = _BACKENDS.get(settings.get("method", "synology"))
    if backend is None:
        raise NasError(f"Método de envío desconocido: {settings.get('method')}")
    backend(files, settings, progress_cb)


def list_folders(settings: dict, path: str = "") -> dict:
    """Subcarpetas de `path` en el NAS. Con `path` vacío devuelve las carpetas compartidas.

    Las compartidas son la raíz de verdad de un Synology: no existe un "/" que se pueda
    listar como en un sistema de ficheros normal, hay que pedirlas con `list_share`.
    """
    method = settings.get("method", "synology")
    path = (path or "").strip()

    if method != "synology":
        raise NasError(
            "Explorar carpetas remotas solo está disponible con Synology File Station. "
            "Con SFTP o FTP, escribe la ruta a mano."
        )

    with _SynologySession(settings) as session:
        common = {"_sid": session.sid, "additional": ""}
        if not path or path == "/":
            data = _syno_check(session.post({
                "api": "SYNO.FileStation.List",
                "version": session.api_version("SYNO.FileStation.List"),
                "method": "list_share", "limit": "200", **common,
            }).json(), "Listar carpetas compartidas", "SYNO.FileStation.List")
            entries = data.get("shares", [])
        else:
            data = _syno_check(session.post({
                "api": "SYNO.FileStation.List",
                "version": session.api_version("SYNO.FileStation.List"),
                "method": "list", "folder_path": path,
                "filetype": "dir", "limit": "500", **common,
            }).json(), f"Listar {path}", "SYNO.FileStation.List")
            entries = data.get("files", [])

    folders = sorted(
        ({"name": e.get("name", ""), "path": e.get("path", "")} for e in entries if e.get("path")),
        key=lambda f: f["name"].lower(),
    )
    parent = "" if not path or path == "/" else posixpath.dirname(path.rstrip("/"))
    return {"path": path, "parent": parent if parent != path else "", "folders": folders}


def create_folder(settings: dict, parent: str, name: str) -> dict:
    """Crea una carpeta en el NAS y devuelve su ruta completa."""
    if settings.get("method", "synology") != "synology":
        raise NasError("Crear carpetas remotas solo está disponible con Synology File Station.")

    name = (name or "").strip().strip("/")
    if not name:
        raise NasError("Escribe un nombre para la carpeta.")
    # Los separadores dentro del nombre crearían una jerarquía inesperada a partir de un
    # descuido al teclear.
    if "/" in name or name in (".", ".."):
        raise NasError("El nombre de la carpeta no puede contener «/».")
    if not parent:
        raise NasError(
            "No se pueden crear carpetas compartidas desde aquí. Entra primero en una "
            "carpeta compartida del NAS."
        )

    with _SynologySession(settings) as session:
        payload = session.post({
            "api": "SYNO.FileStation.CreateFolder",
            "version": session.api_version("SYNO.FileStation.CreateFolder"),
            "method": "create", "folder_path": parent, "name": name,
            "force_parent": "false", "_sid": session.sid,
        }).json()
        if not payload.get("success") and (payload.get("error") or {}).get("code") in (408, 1100):
            raise NasError(f"Ya existe una carpeta llamada «{name}» ahí.")
        _syno_check(payload, f"Crear la carpeta {name}", "SYNO.FileStation.CreateFolder")

    return {"path": posixpath.join(parent.rstrip("/"), name)}


def test_connection(settings: dict) -> dict:
    """Comprueba credenciales y acceso a la carpeta remota, sin subir nada."""
    method = settings.get("method", "synology")
    remote_root = settings.get("remote_root", "/photo")

    if method == "synology":
        with _SynologySession(settings) as session:
            try:
                _syno_check(session.post({
                    "api": "SYNO.FileStation.List",
                    "version": session.api_version("SYNO.FileStation.List"), "method": "list",
                    "folder_path": remote_root, "limit": "1", "_sid": session.sid,
                }).json(), f"Leer la carpeta {remote_root}", "SYNO.FileStation.List")
            except NasError as exc:
                # Llegados aquí el login ha ido bien, así que el problema es la carpeta y
                # no las credenciales. Conviene decirlo, porque el reflejo es revisar la
                # contraseña.
                raise NasError(
                    f"La conexión y las credenciales son correctas, pero no se pudo abrir "
                    f"«{remote_root}»: {exc} Usa «Explorar…» para elegir una carpeta "
                    f"válida del NAS."
                ) from exc
            # Se informa de la versión negociada: si algún día falla la subida en un DSM
            # concreto, esto dice de entrada con qué versión se estaba hablando.
            negotiated = session.api_version("SYNO.API.Auth")
            device_id = session.device_id
            remembered = bool(settings.get("otp")) and bool(device_id)

        return {
            "ok": True,
            "message": (
                f"Conexión correcta. La carpeta {remote_root} es accesible "
                f"(API de autenticación versión {negotiated})."
                + (" Este equipo queda registrado como de confianza: no volverá a pedirte "
                   "el código de verificación." if remembered else "")
            ),
            # Quien llama decide si lo guarda; `nas.py` no toca la configuración.
            "device_id": device_id,
        }

    if method == "sftp":
        try:
            import paramiko
        except ImportError as exc:
            raise NasError(
                f"Falta la librería 'paramiko' para SFTP. Instálala con: "
                f"{_como_instalar('paramiko')}"
            ) from exc
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(settings["host"], port=settings.get("port") or DEFAULT_PORTS["sftp"],
                           username=settings["user"], password=settings["password"], timeout=30)
            sftp = client.open_sftp()
            sftp.listdir(remote_root)
            sftp.close()
        except Exception as exc:
            raise NasError(f"SFTP: {_redact(str(exc), settings.get('password', ''))}") from exc
        finally:
            client.close()
        return {"ok": True, "message": f"Conexión SFTP correcta. La carpeta {remote_root} es accesible."}

    try:
        ftp = _ftp_connect(settings)
        ftp.cwd(remote_root)
        ftp.quit()
    except ftplib.all_errors as exc:
        raise NasError(f"FTP: {_redact(str(exc), settings.get('password', ''))}") from exc
    return {"ok": True, "message": f"Conexión FTP correcta. La carpeta {remote_root} es accesible."}
