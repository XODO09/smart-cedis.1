"""Conexión opcional con Google Calendar mediante una cuenta de servicio.

Es opcional: sin configuración, Smart CEDIS funciona igual y la agenda queda solo en el sistema.
Las librerías de Google se importan hasta que hacen falta (ver requirements-google.txt).

Configuración (en este orden de prioridad):
  1. Variables de entorno  GOOGLE_CALENDAR_ID, GOOGLE_CREDENTIALS_FILE, GOOGLE_TIMEZONE
  2. Archivo backend/google_config.json  (ver google_config.example.json)
"""
import importlib.util
import json
import os
import threading
from pathlib import Path

BASE = Path(__file__).parent
ALCANCE = ["https://www.googleapis.com/auth/calendar"]
ZONA_HORARIA = "America/Mexico_City"
TIMEOUT_SEGUNDOS = 12

_prueba = None                       # servicio falso que se inyecta en las pruebas
_cache = {"clave": None, "servicio": None}
_candado = threading.Lock()          # httplib2 no es seguro entre hilos: una llamada a Google a la vez


class ErrorGoogle(Exception):
    """Fallo al hablar con Google; el mensaje está escrito para mostrarse al usuario."""

    def __init__(self, mensaje, http=None):
        super().__init__(mensaje)
        self.http = http


class EventoNoExiste(ErrorGoogle):
    """El evento ya no está en Google Calendar (por ejemplo, lo borraron a mano)."""


def usar_servicio(servicio):
    """Solo para pruebas: usa un servicio falso en lugar de Google (None lo quita)."""
    global _prueba
    _prueba = servicio


# ---------------------------------------------------------------- configuración

def leer_config():
    cfg = {"calendar_id": None, "credentials_file": None, "timezone": None}
    archivo = BASE / "google_config.json"
    if archivo.is_file():
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            datos = {}
        if isinstance(datos, dict):
            for clave in cfg:
                if isinstance(datos.get(clave), str) and datos[clave].strip():
                    cfg[clave] = datos[clave].strip()
    for clave, variable in (("calendar_id", "GOOGLE_CALENDAR_ID"), ("credentials_file", "GOOGLE_CREDENTIALS_FILE"),
                            ("timezone", "GOOGLE_TIMEZONE")):
        if os.environ.get(variable, "").strip():
            cfg[clave] = os.environ[variable].strip()
    ruta = Path(cfg["credentials_file"] or "google-credentials.json").expanduser()
    cfg["credentials_path"] = ruta if ruta.is_absolute() else BASE / ruta
    cfg["timezone"] = cfg["timezone"] or ZONA_HORARIA
    return cfg


def _libreria_instalada():
    try:
        return all(importlib.util.find_spec(m) is not None
                   for m in ("googleapiclient", "google.oauth2", "google_auth_httplib2", "httplib2"))
    except ImportError:
        return False


def requisitos():
    cfg = leer_config()
    return {"calendar_id": bool(cfg["calendar_id"]),
            "credenciales": cfg["credentials_path"].is_file(),
            "libreria": _libreria_instalada()}


def configurado():
    return _prueba is not None or all(requisitos().values())


def _calendario_id():
    return leer_config()["calendar_id"] or "calendario-de-prueba"


def _correo_servicio(ruta):
    try:
        return json.loads(ruta.read_text(encoding="utf-8")).get("client_email")
    except (OSError, ValueError, AttributeError):
        return None


def estado(probar=False):
    """Estado de la conexión; con probar=True también intenta leer el calendario en Google."""
    cfg = leer_config()
    req = requisitos()
    info = {
        "configurado": configurado(),
        "requisitos": req,
        "calendario_id": cfg["calendar_id"],
        "correo_servicio": _correo_servicio(cfg["credentials_path"]) if req["credenciales"] else None,
        "zona_horaria": cfg["timezone"],
        "conectado": None,
        "calendario": None,
        "error": None,
    }
    if probar:
        if not info["configurado"]:
            faltan = [nombre for clave, nombre in (("calendar_id", "el ID del calendario"),
                                                   ("credenciales", "el archivo de credenciales"),
                                                   ("libreria", "las librerías de Google")) if not req[clave]]
            info["conectado"] = False
            info["error"] = "Falta configurar " + ", ".join(faltan) + "."
        else:
            try:
                info["calendario"] = probar_conexion()
                info["conectado"] = True
            except ErrorGoogle as e:
                info["conectado"] = False
                info["error"] = str(e)
    return info


# ----------------------------------------------------------------- cliente de Google

def _servicio():
    if _prueba is not None:
        return _prueba
    ruta = leer_config()["credentials_path"]
    if not ruta.is_file():
        raise ErrorGoogle(f"No se encontró el archivo de credenciales ({ruta.name}).")
    clave = (str(ruta), ruta.stat().st_mtime)
    if _cache["clave"] == clave:
        return _cache["servicio"]
    try:
        import httplib2
        from google.oauth2 import service_account
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build
    except ImportError:
        raise ErrorGoogle("Faltan las librerías de Google. Instálalas con: pip3 install -r requirements-google.txt")
    try:
        credenciales = service_account.Credentials.from_service_account_file(str(ruta), scopes=ALCANCE)
        http = AuthorizedHttp(credenciales, http=httplib2.Http(timeout=TIMEOUT_SEGUNDOS))
        servicio = build("calendar", "v3", http=http, cache_discovery=False)
    except (OSError, ValueError) as e:
        raise ErrorGoogle(f"El archivo de credenciales no es válido: {e}")
    _cache["clave"], _cache["servicio"] = clave, servicio
    return servicio


def _traducir(exc):
    """Convierte cualquier excepción de las librerías de Google en un ErrorGoogle legible."""
    try:
        http = int(getattr(getattr(exc, "resp", None), "status", None))
    except (TypeError, ValueError):
        http = None
    nombre = type(exc).__name__
    if http in (404, 410):
        return EventoNoExiste("No se encontró el calendario o el evento. Revisa el ID del calendario y que esté "
                              "compartido con la cuenta de servicio.", http)
    if http == 403:
        return ErrorGoogle("Google negó el acceso. Comparte el calendario con la cuenta de servicio con el permiso "
                           "«Hacer cambios en eventos» y confirma que la API de Google Calendar esté habilitada "
                           "en tu proyecto.", http)
    if http == 401 or nombre == "RefreshError":
        return ErrorGoogle("Google rechazó las credenciales de la cuenta de servicio. Descarga una llave JSON nueva "
                           "y revisa que la fecha y hora de tu computadora sean correctas.", http)
    if http == 429:
        return ErrorGoogle("Google limitó temporalmente las solicitudes; se reintentará más tarde.", http)
    if isinstance(exc, OSError) or "ServerNotFound" in nombre or nombre in ("TransportError", "HttpLib2Error"):
        return ErrorGoogle("No se pudo conectar con Google. Revisa tu conexión a internet.")
    return ErrorGoogle(f"Error de Google ({http or nombre}): {exc}", http)


def _llamar(funcion):
    """Ejecuta `funcion(servicio, calendario_id)` de forma segura entre hilos y traduce los errores."""
    with _candado:
        try:
            return funcion(_servicio(), _calendario_id())
        except ErrorGoogle:
            raise
        except Exception as exc:  # noqa: BLE001  (las librerías de Google lanzan tipos muy variados)
            raise _traducir(exc) from exc


def crear_evento(evento):
    """Crea el evento y devuelve {"id": ..., "link": ...}."""
    r = _llamar(lambda s, cal: s.events().insert(calendarId=cal, body=evento).execute())
    return {"id": r["id"], "link": r.get("htmlLink")}


def actualizar_evento(event_id, evento):
    """Cambia un evento existente. Lanza EventoNoExiste si ya no está en Google."""
    r = _llamar(lambda s, cal: s.events().patch(calendarId=cal, eventId=event_id, body=evento).execute())
    return {"id": r.get("id", event_id), "link": r.get("htmlLink")}


def eliminar_evento(event_id):
    """Borra el evento; si ya no existe, no es un error."""
    try:
        _llamar(lambda s, cal: s.events().delete(calendarId=cal, eventId=event_id).execute())
    except EventoNoExiste:
        pass


def probar_conexion():
    """Lee el calendario configurado y devuelve su nombre (confirma ID, permisos y credenciales)."""
    r = _llamar(lambda s, cal: s.calendars().get(calendarId=cal).execute())
    return r.get("summary") or r.get("id")
