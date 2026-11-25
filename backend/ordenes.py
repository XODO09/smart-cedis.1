"""Órdenes de compra, desglose de factura por bulto y descarga con terminal portátil.

Reglas del CEDIS que se cubren aquí:
  * cada OC lleva un folio de factura propio, que no se puede repetir;
  * la factura se desglosa por bulto (caja): producto, piezas, peso y volumen, sin mezclar productos;
  * cada bulto lleva una etiqueta QR (bulto, OC, proveedor, sucursal destino, SKU y piezas);
  * al descargar se escanea cada bulto; lo no solicitado (otro SKU, excedente, otra OC) se reporta y no se recibe.
"""
import sqlite3

import services
from comun import ErrorNegocio, ahora
from database import conexion

# Una tarima se arma con bultos de un mismo producto y de una misma OC, sin pasar de estos límites
TARIMA_MAX_KG = 1000
TARIMA_MAX_M3 = 1.8
MAX_BULTOS_POR_LINEA = 500


def codigo_bulto(bulto_id):
    return f"B-{bulto_id:06d}"


def payload_qr(b):
    """Texto del QR de un bulto: bulto | OC | proveedor | sucursal destino | SKU | piezas."""
    return f"{b['codigo']}|{b['oc_folio']}|PRV{b['proveedor_id']}|SUC{b['sucursal_id']}|{b['sku']}|{b['piezas']}"


def _texto(valor, campo):
    valor = (str(valor) if valor is not None else "").strip().upper()
    if not valor:
        raise ErrorNegocio(f"Escribe {campo}.")
    return valor


def _numero(valor, campo, entero=False, maximo=None):
    try:
        n = int(valor) if entero else float(valor)
    except (TypeError, ValueError):
        raise ErrorNegocio(f"{campo} debe ser un número.")
    if n <= 0 or (maximo and n > maximo):
        raise ErrorNegocio(f"{campo} debe ser mayor a cero" + (f" y no pasar de {maximo}." if maximo else "."))
    return n


# ------------------------------------------------------------------ alta de OC

def crear_orden(datos, operador="operador"):
    """Alta de una OC con su factura desglosada por bulto.

    `datos`: folio, folio_factura, proveedor_id, sucursal_id y `lineas`: lista de
    {sku, piezas_solicitadas (opcional), bultos, piezas_por_bulto, peso_kg, volumen_m3} (peso y volumen de cada bulto).
    """
    folio = _texto(datos.get("folio"), "el folio de la OC")
    factura = _texto(datos.get("folio_factura"), "el folio de la factura")
    lineas = datos.get("lineas") or []
    if not lineas:
        raise ErrorNegocio("La OC debe incluir al menos un producto.")
    with conexion() as conn:
        if conn.execute("SELECT 1 FROM proveedores WHERE id = ?", (datos.get("proveedor_id"),)).fetchone() is None:
            raise ErrorNegocio("Elige el proveedor de la OC.")
        if conn.execute("SELECT 1 FROM sucursales WHERE id = ?", (datos.get("sucursal_id"),)).fetchone() is None:
            raise ErrorNegocio("Elige la sucursal de destino.")
        previa = conn.execute("SELECT folio FROM ordenes_compra WHERE folio_factura = ?", (factura,)).fetchone()
        if previa:
            raise ErrorNegocio(f"El folio de factura {factura} ya está relacionado con la OC {previa['folio']}; "
                               "no se puede repetir.")
        if conn.execute("SELECT 1 FROM ordenes_compra WHERE folio = ?", (folio,)).fetchone():
            raise ErrorNegocio(f"Ya existe una OC con el folio {folio}.")

        productos, vistos, preparadas = {}, set(), []
        for i, l in enumerate(lineas, 1):
            sku = (l.get("sku") or "").strip()
            fila = conn.execute("SELECT id FROM productos WHERE sku = ?", (sku,)).fetchone()
            if fila is None:
                raise ErrorNegocio(f"Línea {i}: elige un producto del catálogo.")
            if sku in vistos:
                raise ErrorNegocio(f"El producto {sku} aparece en dos líneas; júntalas en una.")
            vistos.add(sku)
            bultos = _numero(l.get("bultos"), f"Línea {i}: los bultos", entero=True, maximo=MAX_BULTOS_POR_LINEA)
            por_bulto = _numero(l.get("piezas_por_bulto"), f"Línea {i}: las piezas por bulto", entero=True)
            peso = _numero(l.get("peso_kg"), f"Línea {i}: el peso por bulto")
            volumen = _numero(l.get("volumen_m3"), f"Línea {i}: el volumen por bulto")
            facturadas = bultos * por_bulto
            solicitadas = facturadas
            if l.get("piezas_solicitadas") not in (None, ""):
                solicitadas = _numero(l["piezas_solicitadas"], f"Línea {i}: las piezas solicitadas", entero=True)
            if facturadas > solicitadas:
                raise ErrorNegocio(f"{sku}: la factura trae {facturadas} piezas y la OC solo pidió {solicitadas}; "
                                   "no se factura mercancía no solicitada.")
            preparadas.append((fila["id"], solicitadas, bultos, por_bulto, peso, volumen))

        oc_id = conn.execute(
            "INSERT INTO ordenes_compra (folio, folio_factura, proveedor_id, sucursal_id, creada, operador) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (folio, factura, datos["proveedor_id"], datos["sucursal_id"], ahora(), operador)).lastrowid
        for producto_id, solicitadas, bultos, por_bulto, peso, volumen in preparadas:
            conn.execute("INSERT INTO oc_lineas (oc_id, producto_id, piezas) VALUES (?, ?, ?)",
                         (oc_id, producto_id, solicitadas))
            for _ in range(bultos):
                bid = conn.execute(
                    "INSERT INTO bultos (oc_id, producto_id, piezas, peso_kg, volumen_m3) VALUES (?, ?, ?, ?, ?)",
                    (oc_id, producto_id, por_bulto, peso, volumen)).lastrowid
                conn.execute("UPDATE bultos SET codigo = ? WHERE id = ?", (codigo_bulto(bid), bid))
    return obtener_orden(oc_id)


# ---------------------------------------------------------------- consultas

_ORDEN = ("SELECT o.id, o.folio, o.folio_factura, o.estado, o.creada, o.proveedor_id, o.sucursal_id, "
          "       p.nombre AS proveedor, s.nombre AS sucursal, s.destino, "
          "       (SELECT COUNT(*) FROM bultos b WHERE b.oc_id = o.id) AS bultos, "
          "       (SELECT COUNT(*) FROM bultos b WHERE b.oc_id = o.id AND b.estado = 'recibido') AS recibidos, "
          "       (SELECT COUNT(*) FROM bultos b WHERE b.oc_id = o.id AND b.estado = 'escaneado') AS escaneados, "
          "       (SELECT c.id FROM citas c WHERE c.oc_id = o.id AND c.estado = 'programada' LIMIT 1) AS cita_id, "
          "       (SELECT c.inicio FROM citas c WHERE c.oc_id = o.id AND c.estado = 'programada' LIMIT 1) AS cita_inicio "
          "FROM ordenes_compra o JOIN proveedores p ON p.id = o.proveedor_id "
          "JOIN sucursales s ON s.id = o.sucursal_id ")


def listar_ordenes(estado=None):
    with conexion() as conn:
        sql, par = _ORDEN, []
        if estado:
            sql += "WHERE o.estado = ? "
            par.append(estado)
        return [dict(f) for f in conn.execute(sql + "ORDER BY o.id DESC", par).fetchall()]


def obtener_orden(oc_id):
    with conexion() as conn:
        fila = conn.execute(_ORDEN + "WHERE o.id = ?", (oc_id,)).fetchone()
        if fila is None:
            raise ErrorNegocio(f"La orden de compra {oc_id} no existe.")
        orden = dict(fila)
        orden["lineas"] = [dict(f) for f in conn.execute(
            "SELECT p.sku, p.nombre AS producto, l.piezas AS solicitadas, "
            "       COUNT(b.id) AS bultos, COALESCE(SUM(b.piezas), 0) AS facturadas, "
            "       COALESCE(SUM(b.peso_kg), 0) AS peso_kg, COALESCE(SUM(b.volumen_m3), 0) AS volumen_m3, "
            "       SUM(b.estado = 'recibido') AS recibidos, SUM(b.estado = 'escaneado') AS escaneados "
            "FROM oc_lineas l JOIN productos p ON p.id = l.producto_id "
            "LEFT JOIN bultos b ON b.oc_id = l.oc_id AND b.producto_id = l.producto_id "
            "WHERE l.oc_id = ? GROUP BY l.id ORDER BY p.sku", (oc_id,)).fetchall()]
        orden["peso_kg"] = round(sum(l["peso_kg"] for l in orden["lineas"]), 1)
        orden["volumen_m3"] = round(sum(l["volumen_m3"] for l in orden["lineas"]), 2)
        return orden


def _bultos_con_datos(conn, filtro, parametros):
    return [dict(f) for f in conn.execute(
        "SELECT b.id, b.codigo, b.piezas, b.peso_kg, b.volumen_m3, b.estado, p.sku, p.nombre AS producto, "
        "       o.folio AS oc_folio, o.folio_factura, o.proveedor_id, o.sucursal_id, pr.nombre AS proveedor, "
        "       s.nombre AS sucursal "
        "FROM bultos b JOIN productos p ON p.id = b.producto_id JOIN ordenes_compra o ON o.id = b.oc_id "
        "JOIN proveedores pr ON pr.id = o.proveedor_id JOIN sucursales s ON s.id = o.sucursal_id "
        f"WHERE {filtro} ORDER BY b.id", parametros).fetchall()]


def datos_etiquetas_bultos(oc_id=None, codigo=None):
    """Bultos (con el texto de su QR) para imprimir las etiquetas que el proveedor pega en cada caja."""
    with conexion() as conn:
        if (oc_id is None) == (codigo is None):
            raise ValueError("Indica la OC o el código del bulto, no ambos.")
        filas = (_bultos_con_datos(conn, "b.oc_id = ?", (oc_id,)) if codigo is None
                 else _bultos_con_datos(conn, "b.codigo = ?", (codigo,)))
    if not filas:
        raise ErrorNegocio("No hay bultos para esa OC." if codigo is None else f"El bulto {codigo} no existe.")
    for f in filas:
        f["qr"] = payload_qr(f)
    return filas


# ------------------------------------------------------------ descarga (terminal)

def _cita_de_descarga(conn, cita_id):
    cita = conn.execute("SELECT * FROM citas WHERE id = ?", (cita_id,)).fetchone()
    if cita is None:
        raise ErrorNegocio(f"La cita {cita_id} no existe.")
    if cita["tipo"] != "llegada":
        raise ErrorNegocio("Solo las citas de llegada tienen descarga.")
    if cita["estado"] != "programada":
        raise ErrorNegocio(f"La cita {cita_id} ya está {cita['estado']}.")
    if not cita["oc_id"]:
        raise ErrorNegocio("Esta cita no tiene una OC ligada; edítala y elige la orden de compra que viene en el camión.")
    return cita


def estado_descarga(cita_id):
    """Avance de la descarga: lo esperado vs. lo escaneado, y lo rechazado."""
    with conexion() as conn:
        cita = _cita_de_descarga(conn, cita_id)
        bultos = _bultos_con_datos(conn, "b.oc_id = ?", (cita["oc_id"],))
        incidencias = [dict(f) for f in conn.execute(
            "SELECT codigo, motivo, fecha FROM incidencias WHERE cita_id = ? ORDER BY id DESC", (cita_id,)).fetchall()]
    orden = obtener_orden(cita["oc_id"])
    pendientes = [b for b in bultos if b["estado"] == "esperado"]
    return {
        "cita_id": cita_id, "placas": cita["placas"], "orden": orden,
        "esperados": len(bultos), "escaneados": sum(b["estado"] != "esperado" for b in bultos),
        "pendientes": [{"codigo": b["codigo"], "sku": b["sku"], "piezas": b["piezas"], "qr": payload_qr(b)}
                       for b in pendientes],
        "por_sku": orden["lineas"], "incidencias": incidencias,
    }


def _rechazar(cita, codigo, motivo, operador, tipo):
    with conexion() as conn:
        conn.execute("INSERT INTO incidencias (cita_id, oc_id, codigo, motivo, fecha, operador, tipo) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (cita["id"], cita["oc_id"], codigo[:60], motivo, ahora(), operador, tipo))
    return {"aceptado": False, "motivo": motivo, "codigo": codigo, "bulto": None, "progreso": estado_descarga(cita["id"])}


def escanear_bulto(cita_id, lectura, operador="operador"):
    """Registra un escaneo de la terminal portátil. Un bulto no solicitado se reporta y no se recibe."""
    with conexion() as conn:
        cita = dict(_cita_de_descarga(conn, cita_id))
    lectura = (lectura or "").strip()
    if not lectura:
        raise ErrorNegocio("El escaneo llegó vacío.")
    codigo = lectura.split("|")[0].strip().upper()
    with conexion() as conn:
        bultos = _bultos_con_datos(conn, "b.codigo = ?", (codigo,))
        cita_oc_folio = conn.execute("SELECT folio FROM ordenes_compra WHERE id = ?", (cita["oc_id"],)).fetchone()["folio"]
    if not bultos:
        return _rechazar(cita, codigo, "No recibido: el bulto no existe en el sistema (mercancía no solicitada o excedente).", operador, "no_existe")
    b = bultos[0]
    if b["oc_folio"] != cita_oc_folio:
        return _rechazar(cita, codigo, f"No recibido: pertenece a la OC {b['oc_folio']}, no a la de esta descarga.", operador, "otra_oc")
    if lectura.upper() != codigo and lectura.upper() != payload_qr(b).upper():
        return _rechazar(cita, codigo, "No recibido: los datos de la etiqueta no coinciden con el registro del bulto (otro SKU o cantidad).", operador, "etiqueta")
    if b["estado"] != "esperado":
        return _rechazar(cita, codigo, "No recibido: este bulto ya fue escaneado (excedente).", operador, "repetido")
    with conexion() as conn:
        conn.execute("UPDATE bultos SET estado = 'escaneado', escaneado = ? WHERE id = ?", (ahora(), b["id"]))
    return {"aceptado": True, "motivo": None, "codigo": codigo, "progreso": estado_descarga(cita_id),
            "bulto": {"codigo": b["codigo"], "sku": b["sku"], "producto": b["producto"], "piezas": b["piezas"]}}


def _armar_tarimas(bultos, sucursal_id, oc_id):
    """Agrupa los bultos escaneados en tarimas: mismo producto, sin pasar de peso ni volumen máximos."""
    tarimas, por_sku = [], {}
    for b in bultos:
        por_sku.setdefault(b["sku"], []).append(b)
    for sku, lista in por_sku.items():
        actual = None
        for b in lista:
            if actual is None or actual["peso_kg"] + b["peso_kg"] > TARIMA_MAX_KG or \
                    actual["volumen_m3"] + b["volumen_m3"] > TARIMA_MAX_M3:
                actual = {"sku": sku, "cantidad": 0, "peso_kg": 0.0, "volumen_m3": 0.0, "bultos": [],
                          "sucursal_id": sucursal_id, "oc_id": oc_id}
                tarimas.append(actual)
            actual["cantidad"] += b["piezas"]
            actual["peso_kg"] = round(actual["peso_kg"] + b["peso_kg"], 2)
            actual["volumen_m3"] = round(actual["volumen_m3"] + b["volumen_m3"], 3)
            actual["bultos"].append(b["id"])
    return tarimas


def cerrar_descarga(cita_id, placas, base_tarima, film_seguridad, altura_maxima, operador="operador"):
    """Termina la descarga: arma las tarimas con los bultos escaneados y registra la recepción."""
    if not (base_tarima and film_seguridad and altura_maxima):
        raise ErrorNegocio("Confirma que la mercancía conserva la base de la tarima, viene sujeta con film de "
                           "seguridad y no rebasa la altura máxima antes de cerrar la descarga.")
    placas = (placas or "").strip().upper()
    if not placas:
        raise ErrorNegocio("Escribe las placas del camión.")
    with conexion() as conn:
        cita = dict(_cita_de_descarga(conn, cita_id))
        orden = conn.execute("SELECT * FROM ordenes_compra WHERE id = ?", (cita["oc_id"],)).fetchone()
        escaneados = _bultos_con_datos(conn, "b.oc_id = ? AND b.estado = 'escaneado'", (cita["oc_id"],))
        rechazos = conn.execute("SELECT COUNT(*) FROM incidencias WHERE cita_id = ?", (cita_id,)).fetchone()[0]
    if not escaneados:
        raise ErrorNegocio("Todavía no se ha escaneado ningún bulto.")

    tarimas = _armar_tarimas(escaneados, orden["sucursal_id"], orden["id"])
    r = services.registrar_recepcion(
        placas, orden["proveedor_id"], f"OC {orden['folio']}",
        [{k: v for k, v in t.items() if k != "bultos"} for t in tarimas], operador=operador, cita_id=cita_id)
    with conexion() as conn:
        ids = {c: conn.execute("SELECT id FROM tarimas WHERE codigo = ?", (c,)).fetchone()["id"] for c in r["tarimas"]}
        for codigo_tarima, t in zip(r["tarimas"], tarimas):
            conn.executemany("UPDATE bultos SET estado = 'recibido', tarima_id = ? WHERE id = ?",
                             [(ids[codigo_tarima], bid) for bid in t["bultos"]])
        faltantes = conn.execute("SELECT COUNT(*) FROM bultos WHERE oc_id = ? AND estado = 'esperado'",
                                 (orden["id"],)).fetchone()[0]
        conn.execute("UPDATE ordenes_compra SET estado = ? WHERE id = ?",
                     ("parcial" if faltantes else "recibida", orden["id"]))
    r.update({"bultos_recibidos": len(escaneados), "bultos_faltantes": faltantes, "rechazos": rechazos,
              "oc": orden["folio"], "estado_oc": "parcial" if faltantes else "recibida"})
    return r


# ------------------------------------------------------------------------- demo

def datos_demo():
    """Tres OC pendientes (una por cada cita de llegada de la demo). Devuelve sus ids."""
    # (folio, factura, proveedor, sucursal, [(sku, bultos, piezas por bulto, kg por bulto, m³ por bulto)])
    ordenes = [
        ("OC-2026-0101", "FAC-A-48211", 1, 1, [("SKU-1001", 20, 12, 14.5, 0.045), ("SKU-1002", 15, 20, 21, 0.06)]),
        ("OC-2026-0102", "FAC-B-77310", 2, 2, [("SKU-2001", 18, 24, 18, 0.05), ("SKU-2002", 12, 6, 10, 0.03)]),
        ("OC-2026-0103", "FAC-C-10459", 3, 3, [("SKU-3001", 16, 12, 13, 0.05), ("SKU-3002", 10, 4, 6, 0.12)]),
    ]
    ids = []
    for folio, factura, proveedor, sucursal, lineas in ordenes:
        o = crear_orden({
            "folio": folio, "folio_factura": factura, "proveedor_id": proveedor, "sucursal_id": sucursal,
            "lineas": [{"sku": s, "bultos": b, "piezas_por_bulto": p, "peso_kg": kg, "volumen_m3": m3}
                       for s, b, p, kg, m3 in lineas]}, operador="Demo")
        ids.append(o["id"])
    return ids
