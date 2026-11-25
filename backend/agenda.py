"""Agenda de llegadas (proveedores) y entregas (sucursales) del CEDIS.

Las citas viven en el sistema y, si hay conexión, se reflejan como eventos de Google Calendar.
Si Google falla, la operación del CEDIS no se detiene: la cita queda marcada para reintentar.
"""
from datetime import datetime, timedelta

import gcal
from comun import ErrorNegocio, ahora, codigo_embarque
from database import DURACION_MIN_CITA, HORA_FIN_CITAS, HORA_INICIO_CITAS, NUM_ANDENES, conexion

TIPOS = ("llegada", "entrega")
ESTADOS = ("programada", "completada", "cancelada")
DURACION_MIN, DURACION_MAX = DURACION_MIN_CITA, 480
LIMITE_SINCRONIZACION = 100   # citas por pulsación de "Sincronizar ahora"
DIAS_HISTORIAL_SYNC = 7       # al sincronizar todo no se suben citas terminadas hace más de estos días

SELECCION = (
    "SELECT c.*, p.nombre AS proveedor, s.nombre AS sucursal, s.destino AS destino, e.estado AS embarque_estado, "
    "       o.folio AS oc_folio, o.folio_factura AS oc_factura, o.estado AS oc_estado "
    "FROM citas c LEFT JOIN proveedores p ON p.id = c.proveedor_id "
    "LEFT JOIN ordenes_compra o ON o.id = c.oc_id "
    "LEFT JOIN sucursales s ON s.id = c.sucursal_id LEFT JOIN embarques e ON e.id = c.embarque_id ")


# ---------------------------------------------------------------------- utilidades

def _fecha(texto, campo="La fecha"):
    try:
        dt = datetime.fromisoformat(str(texto).strip())
    except (TypeError, ValueError):
        raise ErrorNegocio(f"{campo} no es válida; usa el formato 2026-11-26T10:00.")
    return dt.replace(microsecond=0, tzinfo=None)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _hora(texto):
    return datetime.fromisoformat(texto).strftime("%H:%M")


def _titulo(c):
    if c["tipo"] == "llegada":
        partes = ["Llegada", c["proveedor"], c["oc_folio"], c["placas"]]
    else:
        partes = ["Entrega", c["sucursal"], codigo_embarque(c["embarque_id"]) if c["embarque_id"] else None]
    return " · ".join(p for p in partes if p)


def _a_dict(fila, ahora_dt=None):
    ahora_dt = ahora_dt or datetime.now()
    c = dict(fila)
    programada = c["estado"] == "programada"
    c["titulo"] = _titulo(c)
    c["embarque_codigo"] = codigo_embarque(c["embarque_id"]) if c["embarque_id"] else None
    c["atrasada"] = programada and datetime.fromisoformat(c["fin"]) < ahora_dt
    c["en_curso"] = programada and datetime.fromisoformat(c["inicio"]) <= ahora_dt < datetime.fromisoformat(c["fin"])
    return c


def _fila(conn, cita_id):
    fila = conn.execute(SELECCION + "WHERE c.id = ?", (cita_id,)).fetchone()
    if fila is None:
        raise ErrorNegocio(f"La cita {cita_id} no existe.")
    return fila


def config():
    return {"andenes": list(range(1, NUM_ANDENES + 1)), "zona_horaria": gcal.leer_config()["timezone"],
            "duracion_min": DURACION_MIN, "duracion_max": DURACION_MAX,
            "hora_inicio": HORA_INICIO_CITAS, "hora_fin": HORA_FIN_CITAS}


# ------------------------------------------------------------------------ validación

def _validar_andenes(conn, anden, inicio, fin, excluir_id):
    """Un andén no puede tener dos citas programadas al mismo tiempo."""
    consulta = ("c.anden = ? AND c.estado = 'programada' AND c.inicio < ? AND c.fin > ? AND c.id != ?")
    choque = conn.execute(SELECCION + f"WHERE {consulta} ORDER BY c.inicio LIMIT 1",
                          (anden, fin, inicio, excluir_id or 0)).fetchone()
    if choque is None:
        return
    c = _a_dict(choque)
    libres = [a for a in range(1, NUM_ANDENES + 1) if a != anden and conn.execute(
        "SELECT 1 FROM citas c WHERE " + consulta, (a, fin, inicio, excluir_id or 0)).fetchone() is None]
    sugerencia = (f" Andenes libres en ese horario: {', '.join(map(str, libres))}." if libres
                  else " No hay andenes libres en ese horario; cambia la hora.")
    raise ErrorNegocio(f"El andén {anden} ya está ocupado de {_hora(c['inicio'])} a {_hora(c['fin'])} "
                       f"por «{c['titulo']}».{sugerencia}")


def _normalizar(conn, datos, cita_id=None):
    """Valida los datos de una cita y devuelve las columnas listas para guardarse."""
    tipo = datos.get("tipo")
    if tipo not in TIPOS:
        raise ErrorNegocio("El tipo de cita debe ser 'llegada' o 'entrega'.")
    inicio = _fecha(datos.get("inicio"), "La fecha de inicio")
    try:
        duracion = int(datos.get("duracion_min") or 60)
    except (TypeError, ValueError):
        raise ErrorNegocio("La duración debe ser un número de minutos.")
    if not DURACION_MIN <= duracion <= DURACION_MAX:
        raise ErrorNegocio(f"La duración debe estar entre {DURACION_MIN} y {DURACION_MAX} minutos.")
    fin = inicio + timedelta(minutes=duracion)
    try:
        anden = int(datos.get("anden") or 0)
    except (TypeError, ValueError):
        anden = 0
    if not 1 <= anden <= NUM_ANDENES:
        raise ErrorNegocio(f"El andén debe estar entre 1 y {NUM_ANDENES}.")

    proveedor_id = sucursal_id = embarque_id = None
    oc_id = (datos.get("oc_id") or None) if tipo == "llegada" else None
    if tipo == "llegada":
        proveedor_id = datos.get("proveedor_id")
        if oc_id:
            proveedor_id = conn.execute("SELECT proveedor_id FROM ordenes_compra WHERE id = ?", (oc_id,)).fetchone()
            proveedor_id = proveedor_id["proveedor_id"] if proveedor_id else None
        if not proveedor_id or conn.execute("SELECT 1 FROM proveedores WHERE id = ?", (proveedor_id,)).fetchone() is None:
            raise ErrorNegocio("Elige el proveedor que llega.")
    else:
        embarque_id = datos.get("embarque_id") or None
        if embarque_id:
            e = conn.execute("SELECT id, estado, sucursal_id FROM embarques WHERE id = ?", (embarque_id,)).fetchone()
            if e is None:
                raise ErrorNegocio(f"El embarque {embarque_id} no existe.")
            if e["estado"] == "despachado":
                raise ErrorNegocio(f"El embarque {codigo_embarque(e['id'])} ya fue despachado.")
            otra = conn.execute("SELECT id FROM citas WHERE embarque_id = ? AND estado = 'programada' AND id != ?",
                                (embarque_id, cita_id or 0)).fetchone()
            if otra:
                raise ErrorNegocio(f"El embarque {codigo_embarque(e['id'])} ya tiene la cita #{otra['id']}.")
            sucursal_id = e["sucursal_id"]  # el destino lo define el embarque
        else:
            sucursal_id = datos.get("sucursal_id")
            if not sucursal_id or conn.execute("SELECT 1 FROM sucursales WHERE id = ?", (sucursal_id,)).fetchone() is None:
                raise ErrorNegocio("Elige la sucursal de destino.")

    esperadas = datos.get("tarimas_esperadas")
    if esperadas not in (None, ""):
        try:
            esperadas = int(esperadas)
        except (TypeError, ValueError):
            esperadas = 0
        if esperadas <= 0:
            raise ErrorNegocio("Las tarimas esperadas deben ser un número mayor a cero.")
    else:
        esperadas = None

    abre = inicio.replace(hour=HORA_INICIO_CITAS, minute=0)
    cierra = inicio.replace(hour=HORA_FIN_CITAS, minute=0)
    if inicio < abre or fin > cierra:
        raise ErrorNegocio(f"Las citas se agendan de {HORA_INICIO_CITAS}:00 a {HORA_FIN_CITAS}:00 el mismo día; "
                           f"esta va de {inicio.strftime('%H:%M')} a {fin.strftime('%H:%M')}.")
    if tipo == "llegada" and oc_id:
        oc = conn.execute("SELECT id, folio, proveedor_id, estado FROM ordenes_compra WHERE id = ?", (oc_id,)).fetchone()
        if oc is None:
            raise ErrorNegocio(f"La orden de compra {oc_id} no existe.")
        if oc["estado"] == "recibida":
            raise ErrorNegocio(f"La OC {oc['folio']} ya fue recibida por completo.")
        otra = conn.execute("SELECT id FROM citas WHERE oc_id = ? AND estado = 'programada' AND id != ?",
                            (oc_id, cita_id or 0)).fetchone()
        if otra:
            raise ErrorNegocio(f"La OC {oc['folio']} ya tiene la cita #{otra['id']}.")
        proveedor_id = oc["proveedor_id"]  # el proveedor lo define la OC
    _validar_andenes(conn, anden, _iso(inicio), _iso(fin), cita_id)
    limpio = lambda t: (t or "").strip() or None  # noqa: E731
    return {
        "tipo": tipo, "inicio": _iso(inicio), "fin": _iso(fin), "anden": anden,
        "proveedor_id": proveedor_id, "sucursal_id": sucursal_id, "embarque_id": embarque_id, "oc_id": oc_id,
        "placas": (limpio(datos.get("placas")) or "").upper() or None,
        "tipo_mercancia": limpio(datos.get("tipo_mercancia")),
        "tarimas_esperadas": esperadas, "notas": limpio(datos.get("notas")),
    }


# ---------------------------------------------------------------------- operaciones

def crear_cita(datos, operador="operador", sincronizar=True):
    with conexion() as conn:
        v = _normalizar(conn, datos)
        cita_id = conn.execute(
            "INSERT INTO citas (tipo, inicio, fin, anden, proveedor_id, sucursal_id, embarque_id, oc_id, placas, "
            "tipo_mercancia, tarimas_esperadas, notas, operador, creada) "
            "VALUES (:tipo, :inicio, :fin, :anden, :proveedor_id, :sucursal_id, :embarque_id, :oc_id, :placas, "
            ":tipo_mercancia, :tarimas_esperadas, :notas, :operador, :creada)",
            {**v, "operador": operador, "creada": ahora()}).lastrowid
    if sincronizar:
        _sincronizar(cita_id)
    return obtener_cita(cita_id)


def obtener_cita(cita_id):
    with conexion() as conn:
        return _a_dict(_fila(conn, cita_id))


def actualizar_cita(cita_id, datos):
    with conexion() as conn:
        actual = _fila(conn, cita_id)
        if actual["estado"] != "programada":
            raise ErrorNegocio(f"Solo se pueden editar citas programadas; esta ya está {actual['estado']}.")
        if datos.get("tipo") != actual["tipo"]:
            raise ErrorNegocio("No se puede cambiar el tipo de una cita; cancélala y crea otra.")
        v = _normalizar(conn, datos, cita_id)
        conn.execute(
            "UPDATE citas SET inicio = :inicio, fin = :fin, anden = :anden, proveedor_id = :proveedor_id, "
            "sucursal_id = :sucursal_id, embarque_id = :embarque_id, oc_id = :oc_id, placas = :placas, "
            "tipo_mercancia = :tipo_mercancia, tarimas_esperadas = :tarimas_esperadas, notas = :notas "
            "WHERE id = :id", {**v, "id": cita_id})
        _marcar_pendiente(conn, cita_id)
    _sincronizar(cita_id)
    return obtener_cita(cita_id)


def _cambiar_estado(cita_id, nuevo):
    with conexion() as conn:
        actual = _fila(conn, cita_id)
        if actual["estado"] != "programada":
            raise ErrorNegocio(f"La cita ya está {actual['estado']}.")
        conn.execute("UPDATE citas SET estado = ? WHERE id = ?", (nuevo, cita_id))
        _marcar_pendiente(conn, cita_id)
    _sincronizar(cita_id)
    return obtener_cita(cita_id)


def cancelar_cita(cita_id):
    return _cambiar_estado(cita_id, "cancelada")


def completar_cita(cita_id):
    return _cambiar_estado(cita_id, "completada")


def listar_citas(desde=None, hasta=None, tipo=None, estado=None):
    """Citas que tocan el rango [desde, hasta). Sin `estado` no se incluyen las canceladas."""
    if tipo is not None and tipo not in TIPOS:
        raise ErrorNegocio("El tipo debe ser 'llegada' o 'entrega'.")
    if estado is not None and estado not in ESTADOS:
        raise ErrorNegocio("El estado debe ser 'programada', 'completada' o 'cancelada'.")
    sql, parametros = SELECCION + "WHERE 1 = 1", []
    if desde:
        sql += " AND c.fin > ?"
        parametros.append(_iso(_fecha(desde, "La fecha 'desde'")))
    if hasta:
        sql += " AND c.inicio < ?"
        parametros.append(_iso(_fecha(hasta, "La fecha 'hasta'")))
    if tipo:
        sql += " AND c.tipo = ?"
        parametros.append(tipo)
    sql += " AND c.estado = ?" if estado else " AND c.estado != 'cancelada'"
    if estado:
        parametros.append(estado)
    with conexion() as conn:
        ahora_dt = datetime.now()
        return [_a_dict(f, ahora_dt) for f in conn.execute(sql + " ORDER BY c.inicio, c.id", parametros).fetchall()]


def resumen():
    """Lo que necesita el dashboard: citas de hoy, atrasadas y las siguientes."""
    ahora_dt = datetime.now().replace(microsecond=0)
    hoy = ahora_dt.replace(hour=0, minute=0, second=0)
    with conexion() as conn:
        delhoy = [_a_dict(f, ahora_dt) for f in conn.execute(
            SELECCION + "WHERE c.estado != 'cancelada' AND c.inicio < ? AND c.fin > ? ORDER BY c.inicio, c.id",
            (_iso(hoy + timedelta(days=1)), _iso(hoy))).fetchall()]
        atrasadas = conn.execute("SELECT COUNT(*) FROM citas WHERE estado = 'programada' AND fin < ?",
                                 (_iso(ahora_dt),)).fetchone()[0]
        proximas = [_a_dict(f, ahora_dt) for f in conn.execute(
            SELECCION + "WHERE c.estado = 'programada' AND c.fin >= ? ORDER BY c.inicio, c.id LIMIT 8",
            (_iso(ahora_dt),)).fetchall()]
    pendientes_hoy = [c for c in delhoy if c["estado"] == "programada"]
    return {
        "ahora": _iso(ahora_dt),
        "hoy": delhoy,
        "llegadas_hoy": sum(c["tipo"] == "llegada" for c in pendientes_hoy),
        "entregas_hoy": sum(c["tipo"] == "entrega" for c in pendientes_hoy),
        "atrasadas": atrasadas,
        "proximas": proximas,
    }


# ------------------------------------------------- enlaces con recepciones y despachos

def validar_cita_llegada(conn, cita_id):
    fila = conn.execute("SELECT tipo, estado FROM citas WHERE id = ?", (cita_id,)).fetchone()
    if fila is None:
        raise ErrorNegocio(f"La cita {cita_id} no existe.")
    if fila["tipo"] != "llegada":
        raise ErrorNegocio(f"La cita {cita_id} es una entrega, no una llegada.")
    if fila["estado"] != "programada":
        raise ErrorNegocio(f"La cita {cita_id} ya está {fila['estado']}.")


def _marcar_pendiente(conn, cita_id):
    """Si la cita ya existe en Google, queda por actualizar."""
    conn.execute("UPDATE citas SET google_estado = 'pendiente' WHERE id = ? AND google_event_id IS NOT NULL",
                 (cita_id,))


def completar_por_recepcion(conn, cita_id, recepcion_id):
    conn.execute("UPDATE citas SET estado = 'completada', recepcion_id = ? WHERE id = ?", (recepcion_id, cita_id))
    _marcar_pendiente(conn, cita_id)


def completar_por_despacho(conn, embarque_id):
    ids = [f["id"] for f in conn.execute(
        "SELECT id FROM citas WHERE embarque_id = ? AND estado = 'programada'", (embarque_id,)).fetchall()]
    for cita_id in ids:
        conn.execute("UPDATE citas SET estado = 'completada' WHERE id = ?", (cita_id,))
        _marcar_pendiente(conn, cita_id)


# --------------------------------------------------------------- Google Calendar

def _evento(c):
    """Cuerpo del evento de Google Calendar para una cita."""
    zona = gcal.leer_config()["timezone"]
    completada = c["estado"] == "completada"
    if c["tipo"] == "llegada":
        lineas = [f"Proveedor: {c['proveedor']}"]
        if c["oc_folio"]:
            lineas.append(f"OC: {c['oc_folio']} · factura {c['oc_factura']}")
        if c["tipo_mercancia"]:
            lineas.append(f"Mercancía: {c['tipo_mercancia']}")
        if c["tarimas_esperadas"]:
            lineas.append(f"Tarimas esperadas: {c['tarimas_esperadas']}")
    else:
        lineas = [f"Sucursal: {c['sucursal']} ({c['destino']})"]
        if c["embarque_codigo"]:
            lineas.append(f"Embarque: {c['embarque_codigo']}")
    if c["placas"]:
        lineas.append(f"Camión: {c['placas']}")
    lineas.append(f"Andén: {c['anden']}")
    if c["notas"]:
        lineas.append(f"Notas: {c['notas']}")
    if completada:
        lineas.append("Estado: completada")
    lineas += ["", f"Smart CEDIS · cita #{c['id']}"]
    return {
        "summary": ("✓ " if completada else "") + c["titulo"],
        "description": "\n".join(lineas),
        "location": f"CEDIS, andén {c['anden']}",
        "start": {"dateTime": c["inicio"], "timeZone": zona},
        "end": {"dateTime": c["fin"], "timeZone": zona},
        "colorId": "8" if completada else ("9" if c["tipo"] == "llegada" else "6"),
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]},
        "extendedProperties": {"private": {"smart_cedis_cita": str(c["id"]), "smart_cedis_tipo": c["tipo"]}},
    }


def _guardar_google(cita_id, estado, event_id, link, error):
    with conexion() as conn:
        conn.execute("UPDATE citas SET google_estado = ?, google_event_id = ?, google_link = ?, google_error = ?, "
                     "google_sync = ? WHERE id = ?", (estado, event_id, link, error, ahora(), cita_id))


def _guardar_error(cita_id, mensaje):
    with conexion() as conn:
        conn.execute("UPDATE citas SET google_estado = 'error', google_error = ?, google_sync = ? WHERE id = ?",
                     (mensaje, ahora(), cita_id))


def _sincronizar(cita_id):
    """Refleja la cita en Google Calendar. Nunca lanza errores: la operación del CEDIS no depende de Google.

    Devuelve 'sincronizado', 'error' o None (sin conexión o nada que hacer).
    """
    if not gcal.configurado():
        return None
    with conexion() as conn:
        fila = conn.execute(SELECCION + "WHERE c.id = ?", (cita_id,)).fetchone()
    if fila is None:
        return None
    c = _a_dict(fila)
    try:
        if c["estado"] == "cancelada":
            if c["google_event_id"]:
                gcal.eliminar_evento(c["google_event_id"])
            _guardar_google(cita_id, None, None, None, None)
            return None
        evento = _evento(c)
        resultado = None
        if c["google_event_id"]:
            try:
                resultado = gcal.actualizar_evento(c["google_event_id"], evento)
            except gcal.EventoNoExiste:
                resultado = None  # lo borraron a mano en Google: se vuelve a crear
        if resultado is None:
            resultado = gcal.crear_evento(evento)
        _guardar_google(cita_id, "sincronizado", resultado["id"], resultado.get("link") or c["google_link"], None)
        return "sincronizado"
    except gcal.ErrorGoogle as e:
        _guardar_error(cita_id, str(e))
    except Exception as e:  # noqa: BLE001  (pase lo que pase, no se interrumpe la operación)
        _guardar_error(cita_id, f"Error inesperado al sincronizar: {e}")
    return "error"


def sincronizar_pendientes():
    """Actualiza en Google las citas que cambiaron por otra vía (recepción o despacho)."""
    if not gcal.configurado():
        return 0
    with conexion() as conn:
        ids = [f["id"] for f in conn.execute("SELECT id FROM citas WHERE google_estado = 'pendiente'").fetchall()]
    return sum(_sincronizar(i) == "sincronizado" for i in ids)


def _por_sincronizar(conn):
    limite = _iso(datetime.now() - timedelta(days=DIAS_HISTORIAL_SYNC))
    return [f["id"] for f in conn.execute(
        "SELECT id FROM citas WHERE (estado IN ('programada', 'completada') AND fin >= ? "
        "AND (google_estado IS NULL OR google_estado != 'sincronizado')) "
        "OR (estado = 'cancelada' AND google_event_id IS NOT NULL) ORDER BY inicio", (limite,)).fetchall()]


def sincronizar_todo():
    """Botón «Sincronizar ahora»: sube a Google las citas que faltan o fallaron."""
    if not gcal.configurado():
        raise ErrorNegocio("Google Calendar no está conectado. Revisa el panel de conexión en la Agenda.")
    with conexion() as conn:
        ids = _por_sincronizar(conn)
    lote, restantes = ids[:LIMITE_SINCRONIZACION], max(0, len(ids) - LIMITE_SINCRONIZACION)
    ok = errores = 0
    primer_error = None
    for cita_id in lote:
        r = _sincronizar(cita_id)
        if r == "error":
            errores += 1
            primer_error = primer_error or obtener_cita(cita_id)["google_error"]
        else:
            ok += 1
    return {"sincronizadas": ok, "errores": errores, "restantes": restantes, "primer_error": primer_error}


def estado_google(probar=False):
    info = gcal.estado(probar)
    with conexion() as conn:
        info["pendientes"] = len(_por_sincronizar(conn))
        info["con_error"] = conn.execute("SELECT COUNT(*) FROM citas WHERE google_estado = 'error'").fetchone()[0]
        info["sincronizadas"] = conn.execute(
            "SELECT COUNT(*) FROM citas WHERE google_estado = 'sincronizado'").fetchone()[0]
    return info


def limpiar_google():
    """Antes de borrar todo (reinicio de la demo) quita de Google los eventos de las citas actuales."""
    if not gcal.configurado():
        return
    try:
        with conexion() as conn:
            ids = [f["google_event_id"] for f in conn.execute(
                "SELECT google_event_id FROM citas WHERE google_event_id IS NOT NULL LIMIT ?",
                (LIMITE_SINCRONIZACION,)).fetchall()]
    except Exception:  # noqa: BLE001  (la tabla puede no existir todavía)
        return
    for event_id in ids:
        try:
            gcal.eliminar_evento(event_id)
        except gcal.ErrorGoogle:
            break  # si Google no responde, no se bloquea el reinicio


# ------------------------------------------------------------------------- demo

def datos_demo(oc_ids=None):
    """Citas de ejemplo repartidas en los próximos días, siempre dentro del horario 8:00-18:00.

    `oc_ids` son órdenes de compra pendientes a las que se ligan las primeras llegadas. No se suben a Google.
    """
    ahora_dt = datetime.now()
    hoy = ahora_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    oc_ids = list(oc_ids or [])
    oc = lambda i: {"oc_id": oc_ids[i]} if i < len(oc_ids) else {}  # noqa: E731

    def dia(n, h, m=0):
        return _iso(hoy + timedelta(days=n, hours=h, minutes=m))

    citas = [
        ("llegada", dia(0, 8), 60, 1, {"proveedor_id": 1, "placas": "TRX-401-A", "tipo_mercancia": "Abarrotes", **oc(0)}),
        ("llegada", dia(0, 12), 90, 2, {"proveedor_id": 2, "placas": "TRX-402-B", "tipo_mercancia": "Bebidas", **oc(1)}),
        ("entrega", dia(0, 14), 60, 3, {"sucursal_id": 1, "placas": "VER-103-C", "notas": "Entrega de pedido semanal"}),
        ("entrega", dia(1, 9), 60, 1, {"sucursal_id": 5, "placas": "VER-102-B"}),
        ("llegada", dia(1, 11), 90, 2, {"proveedor_id": 3, "tipo_mercancia": "Limpieza", **oc(2)}),
        ("entrega", dia(2, 8), 120, 3, {"sucursal_id": 3, "placas": "VER-101-A", "notas": "Requiere montacargas"}),
        ("llegada", dia(2, 10, 30), 60, 1, {"proveedor_id": 1, "tipo_mercancia": "Abarrotes"}),
        ("entrega", dia(3, 14), 60, 4, {"sucursal_id": 4}),
    ]
    for tipo, inicio, minutos, anden, extra in citas:
        crear_cita({"tipo": tipo, "inicio": inicio, "duracion_min": minutos, "anden": anden, **extra},
                   operador="Demo", sincronizar=False)
