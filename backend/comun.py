"""Piezas compartidas por varios módulos del backend (evita importaciones circulares)."""
from datetime import datetime


class ErrorNegocio(Exception):
    """Error de una regla de negocio; la API lo convierte en HTTP 400."""


def ahora():
    """Fecha y hora local como texto ISO (es el formato de todas las fechas de la base)."""
    return datetime.now().isoformat(timespec="seconds")


def codigo_embarque(embarque_id):
    """Folio del embarque; es el contenido de su código QR (las tarimas usan T-000001)."""
    return f"E-{embarque_id:06d}"
