"""Indicadores de control: incidencias de descarga y de recepción en sucursal, y tiempos de operación."""
from datetime import datetime

from comun import codigo_embarque
from database import conexion

TIPOS = {
    "no_existe": "Mercancía no solicitada o excedente",
    "otra_oc": "Bulto de otra OC",
    "etiqueta": "Etiqueta no coincide (SKU/cantidad)",
    "repetido": "Bulto repetido al descargar",
    "ajeno_destino": "No pertenece al embarque (sucursal)",
    "repetido_destino": "Bulto repetido en sucursal",
    "faltante_destino": "Faltante en sucursal",
}


def _segundos(inicio, fin):
    try:
        return max(0, (datetime.fromisoformat(fin) - datetime.fromisoformat(inicio)).total_seconds())
    except (TypeError, ValueError):
        return None


def _promedio(valores):
    valores = [v for v in valores if v is not None]
    return round(sum(valores) / len(valores)) if valores else None


def lista_incidencias(conn, limite=None):
    sql = ("SELECT i.id, i.fecha, i.tipo, i.codigo, i.motivo, i.operador, o.folio AS oc, i.entrega_id, n.embarque_id "
           "FROM incidencias i LEFT JOIN ordenes_compra o ON o.id = i.oc_id LEFT JOIN entregas n ON n.id = i.entrega_id "
           "ORDER BY i.id DESC")
    filas = [dict(f) for f in conn.execute(sql + (f" LIMIT {int(limite)}" if limite else "")).fetchall()]
    for f in filas:
        f["tipo_nombre"] = TIPOS.get(f["tipo"], "Otro")
        f["embarque"] = codigo_embarque(f["embarque_id"]) if f["embarque_id"] else None
        f["origen"] = "Sucursal" if f["entrega_id"] else "Descarga"
    return filas


def resumen():
    with conexion() as conn:
        aceptados = conn.execute("SELECT COUNT(*) FROM bultos WHERE estado IN ('escaneado', 'recibido')").fetchone()[0]
        rechazados = conn.execute("SELECT COUNT(*) FROM incidencias WHERE cita_id IS NOT NULL").fetchone()[0]
        por_tipo = [{"tipo": f["tipo"] or "otro", "nombre": TIPOS.get(f["tipo"], "Otro"), "total": f["n"]}
                    for f in conn.execute("SELECT tipo, COUNT(*) AS n FROM incidencias GROUP BY tipo ORDER BY n DESC")]
        parciales = [dict(f) for f in conn.execute(
            "SELECT o.id, o.folio, p.nombre AS proveedor, s.nombre AS sucursal, "
            "       (SELECT COUNT(*) FROM bultos b WHERE b.oc_id = o.id AND b.estado = 'esperado') AS faltantes, "
            "       (SELECT COUNT(*) FROM bultos b WHERE b.oc_id = o.id) AS bultos "
            "FROM ordenes_compra o JOIN proveedores p ON p.id = o.proveedor_id JOIN sucursales s ON s.id = o.sucursal_id "
            "WHERE o.estado = 'parcial' ORDER BY o.id DESC")]
        con_faltantes = [dict(f, codigo=codigo_embarque(f["embarque_id"])) for f in conn.execute(
            "SELECT n.id AS entrega_id, n.embarque_id, s.nombre AS sucursal, n.esperados, n.recibidos "
            "FROM entregas n JOIN embarques e ON e.id = n.embarque_id JOIN sucursales s ON s.id = e.sucursal_id "
            "WHERE n.estado = 'cerrada' AND n.recibidos < n.esperados ORDER BY n.id DESC")]
        tiempos_descarga = [_segundos(f["ini"], f["fin"]) for f in conn.execute(
            "SELECT MIN(b.escaneado) AS ini, MAX(r.fecha_llegada) AS fin FROM bultos b "
            "JOIN tarimas t ON t.id = b.tarima_id JOIN recepciones r ON r.id = t.recepcion_id GROUP BY b.oc_id")]
        tiempos_sucursal = [_segundos(f["inicio"], f["cierre"]) for f in conn.execute(
            "SELECT inicio, cierre FROM entregas WHERE estado = 'cerrada'")]
        entregas_cerradas = conn.execute("SELECT COUNT(*) FROM entregas WHERE estado = 'cerrada'").fetchone()[0]
        lista = lista_incidencias(conn, 200)
    total = aceptados + rechazados
    return {
        "kpis": {
            "bultos_aceptados": aceptados, "bultos_rechazados": rechazados,
            "exactitud_pct": round(100 * aceptados / total, 1) if total else None,
            "incidencias_total": sum(t["total"] for t in por_tipo),
            "ocs_parciales": len(parciales), "entregas_con_faltantes": len(con_faltantes),
            "entregas_cerradas": entregas_cerradas,
            "descarga_promedio_seg": _promedio(tiempos_descarga),
            "sucursal_promedio_seg": _promedio(tiempos_sucursal),
        },
        "por_tipo": por_tipo, "ocs_parciales": parciales, "entregas_con_faltantes": con_faltantes, "lista": lista,
    }
