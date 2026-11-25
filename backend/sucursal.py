"""Recepción de la mercancía en la sucursal destino.

Se escanea el QR de la relación de embarque (E-000001) y después cada bulto (o tarima, si no viene
de una OC) que baja del camión. Lo que no pertenece al embarque se reporta; lo que no llega, se
reporta como faltante al cerrar.
"""
import re

from comun import ErrorNegocio, ahora, codigo_embarque
from database import conexion


def _esperados(conn, embarque_id):
    bultos = [{"codigo": f["codigo"], "tipo": "bulto", "detalle": f"{f['sku']} · {f['piezas']} pzas · {f['tarima']}"}
              for f in conn.execute(
                  "SELECT b.codigo, p.sku, b.piezas, t.codigo AS tarima FROM bultos b "
                  "JOIN tarimas t ON t.id = b.tarima_id JOIN embarque_tarimas et ON et.tarima_id = t.id "
                  "JOIN productos p ON p.id = b.producto_id WHERE et.embarque_id = ? ORDER BY b.id", (embarque_id,))]
    tarimas = [{"codigo": f["codigo"], "tipo": "tarima", "detalle": f"{f['sku']} · {f['cantidad']} unidades"}
               for f in conn.execute(
                   "SELECT t.codigo, p.sku, t.cantidad FROM embarque_tarimas et JOIN tarimas t ON t.id = et.tarima_id "
                   "JOIN productos p ON p.id = t.producto_id "
                   "WHERE et.embarque_id = ? AND NOT EXISTS (SELECT 1 FROM bultos b WHERE b.tarima_id = t.id) "
                   "ORDER BY t.id", (embarque_id,))]
    return bultos + tarimas


def _entrega(conn, entrega_id):
    fila = conn.execute("SELECT * FROM entregas WHERE id = ?", (entrega_id,)).fetchone()
    if fila is None:
        raise ErrorNegocio(f"La recepción en sucursal {entrega_id} no existe.")
    return fila


def listar():
    """Embarques ya despachados y cómo va su recepción en destino."""
    with conexion() as conn:
        return [dict(f, codigo=codigo_embarque(f["embarque_id"])) for f in conn.execute(
            "SELECT e.id AS embarque_id, s.nombre AS sucursal, c.placas, e.fecha_salida, "
            "       n.id AS entrega_id, COALESCE(n.estado, 'sin_recibir') AS estado, n.esperados, n.recibidos, "
            "       (SELECT COUNT(*) FROM entrega_items i WHERE i.entrega_id = n.id) AS escaneados "
            "FROM embarques e JOIN sucursales s ON s.id = e.sucursal_id LEFT JOIN camiones c ON c.id = e.camion_id "
            "LEFT JOIN entregas n ON n.embarque_id = e.id WHERE e.estado = 'despachado' "
            "ORDER BY e.fecha_salida DESC, e.id DESC").fetchall()]


def abrir(lectura, operador="operador"):
    """Escanea el QR del embarque y abre (o retoma) su recepción en la sucursal."""
    codigo = (lectura or "").strip().upper()
    m = re.fullmatch(r"E-(\d{1,9})", codigo)
    if not m:
        raise ErrorNegocio(f"'{lectura}' no es el QR de un embarque (debe verse como E-000001).")
    embarque_id = int(m.group(1))
    with conexion() as conn:
        e = conn.execute("SELECT estado FROM embarques WHERE id = ?", (embarque_id,)).fetchone()
        if e is None:
            raise ErrorNegocio(f"El embarque {codigo} no existe.")
        if e["estado"] != "despachado":
            raise ErrorNegocio(f"El embarque {codigo} todavía no sale del CEDIS (está {e['estado']}).")
        fila = conn.execute("SELECT id FROM entregas WHERE embarque_id = ?", (embarque_id,)).fetchone()
        entrega_id = fila["id"] if fila else conn.execute(
            "INSERT INTO entregas (embarque_id, inicio, operador) VALUES (?, ?, ?)",
            (embarque_id, ahora(), operador)).lastrowid
    return estado(entrega_id)


def estado(entrega_id):
    with conexion() as conn:
        n = dict(_entrega(conn, entrega_id))
        emb = conn.execute(
            "SELECT s.nombre AS sucursal, s.destino, c.placas, e.fecha_salida FROM embarques e "
            "JOIN sucursales s ON s.id = e.sucursal_id LEFT JOIN camiones c ON c.id = e.camion_id WHERE e.id = ?",
            (n["embarque_id"],)).fetchone()
        esperados = _esperados(conn, n["embarque_id"])
        recibidos = {f["codigo"] for f in conn.execute("SELECT codigo FROM entrega_items WHERE entrega_id = ?", (entrega_id,))}
        incidencias = [dict(f) for f in conn.execute(
            "SELECT codigo, motivo, tipo, fecha FROM incidencias WHERE entrega_id = ? ORDER BY id DESC", (entrega_id,))]
    return {
        "entrega_id": entrega_id, "estado": n["estado"], "embarque_id": n["embarque_id"],
        "codigo": codigo_embarque(n["embarque_id"]), "sucursal": emb["sucursal"], "destino": emb["destino"],
        "placas": emb["placas"], "fecha_salida": emb["fecha_salida"], "observaciones": n["observaciones"],
        "esperados": len(esperados), "escaneados": len(recibidos & {e["codigo"] for e in esperados}),
        "pendientes": [e for e in esperados if e["codigo"] not in recibidos],
        "recibidos": [e for e in esperados if e["codigo"] in recibidos], "incidencias": incidencias,
        "cerrada_esperados": n["esperados"], "cerrada_recibidos": n["recibidos"],
    }


def _incidencia(conn, entrega_id, codigo, motivo, tipo, operador):
    conn.execute("INSERT INTO incidencias (entrega_id, codigo, motivo, tipo, fecha, operador) VALUES (?, ?, ?, ?, ?, ?)",
                 (entrega_id, codigo[:60], motivo, tipo, ahora(), operador))


def escanear(entrega_id, lectura, operador="operador"):
    lectura = (lectura or "").strip()
    if not lectura:
        raise ErrorNegocio("El escaneo llegó vacío.")
    codigo = lectura.split("|")[0].strip().upper()
    with conexion() as conn:
        n = _entrega(conn, entrega_id)
        if n["estado"] != "abierta":
            raise ErrorNegocio("Esta recepción ya fue cerrada.")
        esperados = {e["codigo"]: e for e in _esperados(conn, n["embarque_id"])}
        if codigo not in esperados:
            motivo = "No recibido: no pertenece a este embarque (puede ser de otra sucursal o no estar en la relación)."
            _incidencia(conn, entrega_id, codigo, motivo, "ajeno_destino", operador)
            aceptado, item = False, None
        elif conn.execute("SELECT 1 FROM entrega_items WHERE entrega_id = ? AND codigo = ?", (entrega_id, codigo)).fetchone():
            motivo = "No contado: este bulto ya se escaneó en esta recepción."
            _incidencia(conn, entrega_id, codigo, motivo, "repetido_destino", operador)
            aceptado, item = False, None
        else:
            conn.execute("INSERT INTO entrega_items (entrega_id, codigo, fecha) VALUES (?, ?, ?)", (entrega_id, codigo, ahora()))
            motivo, aceptado, item = None, True, esperados[codigo]
    return {"aceptado": aceptado, "motivo": motivo, "codigo": codigo, "item": item, "progreso": estado(entrega_id)}


def cerrar(entrega_id, observaciones=None, operador="operador"):
    """Cierra la recepción: lo que no se escaneó queda como faltante (incidencia)."""
    with conexion() as conn:
        n = _entrega(conn, entrega_id)
        if n["estado"] != "abierta":
            raise ErrorNegocio("Esta recepción ya fue cerrada.")
        esperados = _esperados(conn, n["embarque_id"])
        vistos = {f["codigo"] for f in conn.execute("SELECT codigo FROM entrega_items WHERE entrega_id = ?", (entrega_id,))}
        faltantes = [e for e in esperados if e["codigo"] not in vistos]
        if not vistos:
            raise ErrorNegocio("Todavía no se ha escaneado ningún bulto.")
        for f in faltantes:
            _incidencia(conn, entrega_id, f["codigo"], f"Faltante: no llegó a la sucursal ({f['detalle']}).",
                        "faltante_destino", operador)
        conn.execute("UPDATE entregas SET estado = 'cerrada', cierre = ?, observaciones = ?, esperados = ?, recibidos = ? "
                     "WHERE id = ?", (ahora(), (observaciones or "").strip() or None, len(esperados), len(vistos), entrega_id))
    return {"entrega_id": entrega_id, "esperados": len(esperados), "recibidos": len(vistos),
            "faltantes": faltantes, "completa": not faltantes}
