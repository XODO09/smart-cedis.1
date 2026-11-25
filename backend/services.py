"""Lógica de negocio de Smart CEDIS (no depende de FastAPI, se puede probar sola)."""
import os
import agenda
import database
from comun import ErrorNegocio, codigo_embarque  # noqa: F401  (se reexportan: otros módulos los usan desde aquí)
from comun import ahora as _ahora
from database import conexion

# Las tarimas de este peso o más solo se ubican en el nivel 1 (piso del rack)
PESO_PESADO_KG = 800


def _registrar_movimiento(conn, tarima_id, tipo, origen, destino, operador):
    conn.execute(
        "INSERT INTO movimientos (tarima_id, tipo, origen, destino, fecha, operador) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tarima_id, tipo, origen, destino, _ahora(), operador))


def _tarima_por_codigo(conn, codigo):
    tarima = conn.execute(
        "SELECT t.*, p.sku FROM tarimas t JOIN productos p ON p.id = t.producto_id "
        "WHERE t.codigo = ?", (codigo,)).fetchone()
    if tarima is None:
        raise ErrorNegocio(f"La tarima {codigo} no existe.")
    return tarima


# ---------------------------------------------------------------- catálogos

_CATALOGOS = {
    "productos": "SELECT id, sku, nombre, descripcion FROM productos ORDER BY sku",
    "sucursales": "SELECT id, nombre, destino FROM sucursales ORDER BY id",
    "proveedores": "SELECT id, nombre FROM proveedores ORDER BY id",
    "camiones": "SELECT id, placas, tipo, capacidad_tarimas, capacidad_kg, capacidad_m3 FROM camiones ORDER BY id",
}


def listar_catalogo(nombre):
    with conexion() as conn:
        return [dict(f) for f in conn.execute(_CATALOGOS[nombre]).fetchall()]


# ---------------------------------------------------------------- recepción

def _ubicar(conn, tarima, operador):
    """Busca la primera ubicación libre (rack por rack) y deja la tarima almacenada.

    Devuelve el código de la ubicación o None si no hay lugar.
    """
    sql = ("SELECT u.id, u.codigo FROM ubicaciones u "
           "WHERE NOT EXISTS (SELECT 1 FROM tarimas t WHERE t.ubicacion_id = u.id)")
    if tarima["peso_kg"] >= PESO_PESADO_KG:
        sql += " AND u.nivel = 1"
    sql += " ORDER BY u.rack_id, u.nivel, u.posicion LIMIT 1"
    ubicacion = conn.execute(sql).fetchone()
    if ubicacion is None:
        return None
    conn.execute(
        "UPDATE tarimas SET ubicacion_id = ?, estado = 'almacenada' WHERE id = ?",
        (ubicacion["id"], tarima["id"]))
    _registrar_movimiento(
        conn, tarima["id"], "almacenamiento", "Andén de recepción", ubicacion["codigo"], operador)
    return ubicacion["codigo"]


def registrar_recepcion(placas, proveedor_id, tipo_mercancia, tarimas,
                        tipo_camion="Torton", capacidad_camion=14,
                        ubicar_automaticamente=True, operador="operador", cita_id=None):
    """Registra la llegada de un camión y sus tarimas.

    `tarimas` es una lista de dicts: {"sku": ..., "cantidad": ..., "peso_kg": ...} y, opcionalmente,
    "volumen_m3", "sucursal_id" (destino) y "oc_id" (orden de compra de origen).
    Si no hay lugar para alguna tarima, la recepción se guarda igual y esa tarima
    queda como 'recibida' (movimiento pendiente).
    Si viene `cita_id`, la cita de llegada de la agenda queda completada y ligada a la recepción.
    """
    if not tarimas:
        raise ErrorNegocio("La recepción debe incluir al menos una tarima.")
    with conexion() as conn:
        if conn.execute("SELECT 1 FROM proveedores WHERE id = ?", (proveedor_id,)).fetchone() is None:
            raise ErrorNegocio(f"El proveedor {proveedor_id} no existe.")
        if cita_id is not None:
            agenda.validar_cita_llegada(conn, cita_id)

        camion = conn.execute("SELECT id FROM camiones WHERE placas = ?", (placas,)).fetchone()
        if camion is None:
            camion_id = conn.execute(
                "INSERT INTO camiones (placas, tipo, capacidad_tarimas, capacidad_kg, capacidad_m3) "
                "VALUES (?, ?, ?, ?, ?)",
                (placas, tipo_camion, capacidad_camion, capacidad_camion * 650, capacidad_camion * 2)).lastrowid
        else:
            camion_id = camion["id"]

        productos = {}
        for linea in tarimas:
            sku = linea["sku"]
            if sku not in productos:
                producto = conn.execute("SELECT id FROM productos WHERE sku = ?", (sku,)).fetchone()
                if producto is None:
                    raise ErrorNegocio(f"El SKU {sku} no existe en el catálogo.")
                productos[sku] = producto["id"]
            if linea["cantidad"] <= 0 or linea["peso_kg"] <= 0:
                raise ErrorNegocio(f"La cantidad y el peso de la tarima de {sku} deben ser mayores a cero.")

        recepcion_id = conn.execute(
            "INSERT INTO recepciones (camion_id, proveedor_id, tipo_mercancia, fecha_llegada, operador) "
            "VALUES (?, ?, ?, ?, ?)",
            (camion_id, proveedor_id, tipo_mercancia, _ahora(), operador)).lastrowid
        if cita_id is not None:
            agenda.completar_por_recepcion(conn, cita_id, recepcion_id)

        codigos = []
        for linea in tarimas:
            tarima_id = conn.execute(
                "INSERT INTO tarimas (producto_id, cantidad, peso_kg, recepcion_id, volumen_m3, sucursal_id, oc_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (productos[linea["sku"]], linea["cantidad"], linea["peso_kg"], recepcion_id,
                 linea.get("volumen_m3") or 1.2, linea.get("sucursal_id"), linea.get("oc_id"))).lastrowid
            codigo = f"T-{tarima_id:06d}"
            conn.execute("UPDATE tarimas SET codigo = ? WHERE id = ?", (codigo, tarima_id))
            _registrar_movimiento(conn, tarima_id, "recepcion", f"Camión {placas}", "Andén de recepción", operador)
            codigos.append(codigo)

        sin_ubicar = list(codigos)
        if ubicar_automaticamente:
            sin_ubicar = []
            for codigo in codigos:
                if _ubicar(conn, _tarima_por_codigo(conn, codigo), operador) is None:
                    sin_ubicar.append(codigo)

        return {
            "recepcion_id": recepcion_id,
            "cita_id": cita_id,
            "placas": placas,
            "tarimas": codigos,
            "ubicadas": len(codigos) - len(sin_ubicar),
            "sin_ubicar": sin_ubicar,
        }


def asignar_ubicacion(codigo_tarima, operador="operador"):
    """Ubica una tarima que quedó en 'recibida'."""
    with conexion() as conn:
        tarima = _tarima_por_codigo(conn, codigo_tarima)
        if tarima["estado"] != "recibida":
            raise ErrorNegocio(f"La tarima {codigo_tarima} ya está {tarima['estado']}.")
        ubicacion = _ubicar(conn, tarima, operador)
        if ubicacion is None:
            raise ErrorNegocio("No hay ubicaciones disponibles para esta tarima.")
        return {"tarima": codigo_tarima, "ubicacion": ubicacion}


def ubicar_recepcion(recepcion_id, operador="operador"):
    """Ubica todas las tarimas pendientes de una recepción."""
    with conexion() as conn:
        if conn.execute("SELECT 1 FROM recepciones WHERE id = ?", (recepcion_id,)).fetchone() is None:
            raise ErrorNegocio(f"La recepción {recepcion_id} no existe.")
        pendientes = conn.execute(
            "SELECT t.*, p.sku FROM tarimas t JOIN productos p ON p.id = t.producto_id "
            "WHERE t.recepcion_id = ? AND t.estado = 'recibida' ORDER BY t.id",
            (recepcion_id,)).fetchall()
        ubicadas, sin_ubicar = [], []
        for tarima in pendientes:
            if _ubicar(conn, tarima, operador) is None:
                sin_ubicar.append(tarima["codigo"])
            else:
                ubicadas.append(tarima["codigo"])
        return {"recepcion_id": recepcion_id, "ubicadas": ubicadas, "sin_ubicar": sin_ubicar}


def listar_recepciones():
    with conexion() as conn:
        filas = conn.execute(
            "SELECT r.id, r.fecha_llegada, c.placas, pr.nombre AS proveedor, r.tipo_mercancia, "
            "       COUNT(t.id) AS tarimas, "
            "       COALESCE(SUM(t.estado = 'recibida'), 0) AS por_ubicar "
            "FROM recepciones r "
            "JOIN camiones c ON c.id = r.camion_id "
            "JOIN proveedores pr ON pr.id = r.proveedor_id "
            "LEFT JOIN tarimas t ON t.recepcion_id = r.id "
            "GROUP BY r.id ORDER BY r.id DESC").fetchall()
        return [dict(f) for f in filas]


# --------------------------------------------------------------- inventario

def inventario(sku=None, estado=None):
    """Tarimas en el CEDIS (sin las despachadas, salvo que se pida ese estado) y resumen por SKU."""
    condiciones = ["t.estado = ?"] if estado else ["t.estado != 'despachada'"]
    parametros = [estado] if estado else []
    if sku:
        condiciones.append("p.sku = ?")
        parametros.append(sku)
    with conexion() as conn:
        detalle = conn.execute(
            "SELECT t.codigo, p.sku, p.nombre AS producto, t.cantidad, t.peso_kg, t.estado, "
            "       u.codigo AS ubicacion, t.recepcion_id "
            "FROM tarimas t JOIN productos p ON p.id = t.producto_id "
            "LEFT JOIN ubicaciones u ON u.id = t.ubicacion_id "
            "WHERE " + " AND ".join(condiciones) + " ORDER BY t.id", parametros).fetchall()
        resumen = conn.execute(
            "SELECT p.sku, p.nombre AS producto, COUNT(*) AS tarimas, SUM(t.cantidad) AS unidades, "
            "       SUM(t.estado = 'almacenada') AS disponibles, SUM(t.estado = 'asignada') AS comprometidas "
            "FROM tarimas t JOIN productos p ON p.id = t.producto_id "
            "WHERE t.estado IN ('almacenada', 'asignada') GROUP BY p.id ORDER BY p.sku").fetchall()
        return {"tarimas": [dict(f) for f in detalle], "resumen": [dict(f) for f in resumen]}


# ---------------------------------------------------------------- embarques

def _embarque(conn, embarque_id):
    embarque = conn.execute(
        "SELECT e.id, e.estado, e.fecha_creacion, e.fecha_salida, e.operador, s.nombre AS sucursal, "
        "       s.destino, c.placas, c.tipo AS tipo_camion "
        "FROM embarques e JOIN sucursales s ON s.id = e.sucursal_id "
        "LEFT JOIN camiones c ON c.id = e.camion_id WHERE e.id = ?", (embarque_id,)).fetchone()
    if embarque is None:
        raise ErrorNegocio(f"El embarque {embarque_id} no existe.")
    return embarque


def _tarimas_embarque(conn, embarque_id):
    return conn.execute(
        "SELECT t.id, t.codigo, p.sku, p.nombre AS producto, t.cantidad, t.peso_kg, t.volumen_m3, t.estado, "
        "       u.codigo AS ubicacion, "
        "       (SELECT m.origen FROM movimientos m WHERE m.tarima_id = t.id "
        "        AND m.tipo = 'asignacion_embarque' ORDER BY m.id DESC LIMIT 1) AS origen "
        "FROM embarque_tarimas et JOIN tarimas t ON t.id = et.tarima_id "
        "JOIN productos p ON p.id = t.producto_id "
        "LEFT JOIN ubicaciones u ON u.id = t.ubicacion_id "
        "WHERE et.embarque_id = ? ORDER BY t.id", (embarque_id,)).fetchall()


def crear_embarque(sucursal_id, items, operador="operador"):
    """Crea una orden para una sucursal y aparta las tarimas (las más antiguas primero).

    `items` es una lista de dicts: {"sku": ..., "tarimas": n}.
    """
    if not items:
        raise ErrorNegocio("El embarque debe incluir al menos un producto.")
    with conexion() as conn:
        sucursal = conn.execute(
            "SELECT id, nombre FROM sucursales WHERE id = ?", (sucursal_id,)).fetchone()
        if sucursal is None:
            raise ErrorNegocio(f"La sucursal {sucursal_id} no existe.")

        elegidas = []
        for item in items:
            cuantas = item["tarimas"]
            if cuantas <= 0:
                raise ErrorNegocio("La cantidad de tarimas por producto debe ser mayor a cero.")
            filas = conn.execute(
                "SELECT t.id, t.codigo, p.sku, u.codigo AS ubicacion "
                "FROM tarimas t JOIN productos p ON p.id = t.producto_id "
                "JOIN ubicaciones u ON u.id = t.ubicacion_id "
                "WHERE p.sku = ? AND t.estado = 'almacenada' "
                "AND (t.sucursal_id IS NULL OR t.sucursal_id = ?) ORDER BY t.id LIMIT ?",
                (item["sku"], sucursal_id, cuantas)).fetchall()
            if len(filas) < cuantas:
                raise ErrorNegocio(
                    f"Solo hay {len(filas)} tarimas disponibles de {item['sku']} para {sucursal['nombre']} "
                    f"y se pidieron {cuantas}.")
            ids = [f["id"] for f in filas]
            conn.execute(
                f"UPDATE tarimas SET estado = 'asignada' WHERE id IN ({','.join('?' * len(ids))})", ids)
            elegidas.extend(filas)

        embarque_id = conn.execute(
            "INSERT INTO embarques (sucursal_id, estado, fecha_creacion, operador) VALUES (?, 'pendiente', ?, ?)",
            (sucursal_id, _ahora(), operador)).lastrowid
        for fila in elegidas:
            conn.execute("INSERT INTO embarque_tarimas (embarque_id, tarima_id) VALUES (?, ?)",
                         (embarque_id, fila["id"]))
            _registrar_movimiento(
                conn, fila["id"], "asignacion_embarque", fila["ubicacion"], f"Embarque #{embarque_id}", operador)

        return {
            "embarque_id": embarque_id,
            "codigo": codigo_embarque(embarque_id),
            "sucursal": sucursal["nombre"],
            "estado": "pendiente",
            "tarimas": [{"codigo": f["codigo"], "sku": f["sku"], "ubicacion": f["ubicacion"]} for f in elegidas],
        }


def _ocupacion(tarimas, camion):
    """Qué tanto del camión cubre la carga, en peso y en volumen, y si alcanza el mínimo para salir."""
    peso = sum(t["peso_kg"] for t in tarimas)
    volumen = sum(t["volumen_m3"] for t in tarimas)
    peso_pct = round(100 * peso / camion["capacidad_kg"], 1)
    volumen_pct = round(100 * volumen / camion["capacidad_m3"], 1)
    minimo = 100 * database.OCUPACION_MINIMA
    cumple = _cumple_minimo(peso_pct, volumen_pct)
    return {"peso_kg": round(peso, 1), "volumen_m3": round(volumen, 2), "peso_pct": peso_pct,
            "volumen_pct": volumen_pct, "cumple_minimo": cumple, "minimo_pct": round(minimo),
            "criterio": database.CRITERIO_OCUPACION}


def _cumple_minimo(peso_pct, volumen_pct):
    minimo = 100 * database.OCUPACION_MINIMA
    if database.CRITERIO_OCUPACION == "ambos":
        return peso_pct >= minimo and volumen_pct >= minimo
    return peso_pct >= minimo or volumen_pct >= minimo


def sugerir_embarque(embarque_id):
    """Para un embarque pendiente: qué camión conviene y qué tarimas faltan para llegar al mínimo de ocupación."""
    with conexion() as conn:
        embarque = _embarque(conn, embarque_id)
        if embarque["estado"] != "pendiente":
            raise ErrorNegocio(f"El embarque #{embarque_id} está {embarque['estado']}; solo se sugiere carga para uno pendiente.")
        sucursal_id = conn.execute("SELECT sucursal_id FROM embarques WHERE id = ?", (embarque_id,)).fetchone()[0]
        actuales = _tarimas_embarque(conn, embarque_id)
        disponibles = conn.execute(
            "SELECT t.id, t.codigo, p.sku, p.nombre AS producto, t.peso_kg, t.volumen_m3 "
            "FROM tarimas t JOIN productos p ON p.id = t.producto_id "
            "WHERE t.estado = 'almacenada' AND (t.sucursal_id IS NULL OR t.sucursal_id = ?) ORDER BY t.id",
            (sucursal_id,)).fetchall()
        camiones = conn.execute(
            "SELECT placas, tipo, capacidad_tarimas, capacidad_kg, capacidad_m3 FROM camiones ORDER BY id").fetchall()

    peso0 = sum(t["peso_kg"] for t in actuales)
    vol0 = sum(t["volumen_m3"] for t in actuales)
    resultado = []
    for cam in camiones:
        pp = round(100 * peso0 / cam["capacidad_kg"], 1)
        vp = round(100 * vol0 / cam["capacidad_m3"], 1)
        item = {"placas": cam["placas"], "tipo": cam["tipo"], "capacidad_tarimas": cam["capacidad_tarimas"],
                "capacidad_kg": cam["capacidad_kg"], "capacidad_m3": cam["capacidad_m3"],
                "peso_pct": pp, "volumen_pct": vp, "agregar": []}
        if len(actuales) > cam["capacidad_tarimas"] or pp > 100 or vp > 100:
            item.update(estado="excede", nota="La carga actual no cabe en este camión.")
        elif _cumple_minimo(pp, vp):
            item.update(estado="cumple", nota="Ya cubre el mínimo para salir.")
        else:
            peso, vol, extras = peso0, vol0, []
            for t in disponibles:
                if len(actuales) + len(extras) + 1 > cam["capacidad_tarimas"]:
                    break
                if peso + t["peso_kg"] > cam["capacidad_kg"] or vol + t["volumen_m3"] > cam["capacidad_m3"]:
                    continue
                peso, vol = peso + t["peso_kg"], vol + t["volumen_m3"]
                extras.append(t)
                if _cumple_minimo(100 * peso / cam["capacidad_kg"], 100 * vol / cam["capacidad_m3"]):
                    break
            pp2, vp2 = round(100 * peso / cam["capacidad_kg"], 1), round(100 * vol / cam["capacidad_m3"], 1)
            if extras and _cumple_minimo(pp2, vp2):
                item.update(estado="agregar", nota=f"Agregando {len(extras)} tarimas llegaría al {max(pp2, vp2)}%.",
                            peso_pct_final=pp2, volumen_pct_final=vp2,
                            agregar=[{"codigo": t["codigo"], "sku": t["sku"], "producto": t["producto"],
                                      "peso_kg": t["peso_kg"], "volumen_m3": t["volumen_m3"]} for t in extras])
            else:
                item.update(estado="insuficiente", nota="No hay tarimas disponibles suficientes para llegar al mínimo.")
        resultado.append(item)
    orden = {"cumple": 0, "agregar": 1, "insuficiente": 2, "excede": 3}
    resultado.sort(key=lambda r: (orden[r["estado"]], len(r["agregar"]), -max(r["peso_pct"], r["volumen_pct"])))
    return {"embarque_id": embarque_id, "tarimas": len(actuales), "peso_kg": round(peso0, 1),
            "volumen_m3": round(vol0, 2), "minimo_pct": round(100 * database.OCUPACION_MINIMA),
            "camiones": resultado}


def agregar_tarimas(embarque_id, codigos, operador="operador"):
    """Suma tarimas disponibles a un embarque pendiente (por ejemplo, las que sugiere `sugerir_embarque`)."""
    if not codigos:
        raise ErrorNegocio("Elige al menos una tarima para agregar.")
    with conexion() as conn:
        embarque = _embarque(conn, embarque_id)
        if embarque["estado"] != "pendiente":
            raise ErrorNegocio(f"El embarque #{embarque_id} está {embarque['estado']} y ya no admite más tarimas.")
        sucursal_id = conn.execute("SELECT sucursal_id FROM embarques WHERE id = ?", (embarque_id,)).fetchone()[0]
        for codigo in codigos:
            t = conn.execute(
                "SELECT t.id, t.estado, t.sucursal_id, u.codigo AS ubicacion FROM tarimas t "
                "LEFT JOIN ubicaciones u ON u.id = t.ubicacion_id WHERE t.codigo = ?", (codigo,)).fetchone()
            if t is None:
                raise ErrorNegocio(f"La tarima {codigo} no existe.")
            if t["estado"] != "almacenada":
                raise ErrorNegocio(f"La tarima {codigo} no está disponible (está {t['estado']}).")
            if t["sucursal_id"] not in (None, sucursal_id):
                raise ErrorNegocio(f"La tarima {codigo} está destinada a otra sucursal.")
            conn.execute("UPDATE tarimas SET estado = 'asignada' WHERE id = ?", (t["id"],))
            conn.execute("INSERT INTO embarque_tarimas (embarque_id, tarima_id) VALUES (?, ?)", (embarque_id, t["id"]))
            _registrar_movimiento(conn, t["id"], "asignacion_embarque", t["ubicacion"], f"Embarque #{embarque_id}", operador)
    return {"embarque_id": embarque_id, "agregadas": len(codigos)}


def validar_embarque(embarque_id, placas_camion, codigos_escaneados=None):
    """Valida la carga: el camión debe existir, tener capacidad y (si se escanea) coincidir con la orden."""
    with conexion() as conn:
        embarque = _embarque(conn, embarque_id)
        if embarque["estado"] != "pendiente":
            raise ErrorNegocio(f"El embarque #{embarque_id} está {embarque['estado']} y no se puede validar.")
        camion = conn.execute(
            "SELECT id, placas, capacidad_tarimas, capacidad_kg, capacidad_m3 FROM camiones WHERE placas = ?",
            (placas_camion,)).fetchone()
        if camion is None:
            raise ErrorNegocio(f"El camión con placas {placas_camion} no está registrado.")

        tarimas = _tarimas_embarque(conn, embarque_id)
        if len(tarimas) > camion["capacidad_tarimas"]:
            raise ErrorNegocio(
                f"El camión {camion['placas']} tiene capacidad para {camion['capacidad_tarimas']} tarimas "
                f"y el embarque lleva {len(tarimas)}.")

        ocupacion = _ocupacion(tarimas, camion)
        if ocupacion["peso_pct"] > 100 or ocupacion["volumen_pct"] > 100:
            raise ErrorNegocio(
                f"El embarque excede la capacidad del camión {camion['placas']}: lleva {ocupacion['peso_kg']:,.0f} kg "
                f"({ocupacion['peso_pct']}% de {camion['capacidad_kg']:,.0f}) y {ocupacion['volumen_m3']:.1f} m³ "
                f"({ocupacion['volumen_pct']}% de {camion['capacidad_m3']:,.0f}).")
        if not ocupacion["cumple_minimo"]:
            minimo = round(100 * database.OCUPACION_MINIMA)
            raise ErrorNegocio(
                f"El camión {camion['placas']} no puede salir: va al {ocupacion['peso_pct']}% en peso y al "
                f"{ocupacion['volumen_pct']}% en volumen, y debe cubrir al menos el {minimo}% de su capacidad "
                f"({'en peso o en volumen' if database.CRITERIO_OCUPACION == 'cualquiera' else 'en peso y en volumen'}). "
                "Agrega más tarimas al embarque o usa un camión más pequeño.")

        if codigos_escaneados is not None:
            esperados = {t["codigo"] for t in tarimas}
            escaneados = set(codigos_escaneados)
            faltan = sorted(esperados - escaneados)
            sobran = sorted(escaneados - esperados)
            if faltan or sobran:
                partes = []
                if faltan:
                    partes.append("faltan: " + ", ".join(faltan))
                if sobran:
                    partes.append("no pertenecen al embarque: " + ", ".join(sobran))
                raise ErrorNegocio("La carga no coincide con la orden (" + "; ".join(partes) + ").")

        conn.execute(
            "UPDATE embarques SET camion_id = ?, estado = 'validado' WHERE id = ?", (camion["id"], embarque_id))
        return {"embarque_id": embarque_id, "estado": "validado", "camion": camion["placas"],
                "tarimas": len(tarimas), "ocupacion": ocupacion}


def despachar_embarque(embarque_id, operador="operador"):
    """Registra la salida del camión: las tarimas se descuentan del inventario y liberan su ubicación."""
    with conexion() as conn:
        embarque = _embarque(conn, embarque_id)
        if embarque["estado"] != "validado":
            raise ErrorNegocio(
                f"Solo se puede despachar un embarque validado; el embarque #{embarque_id} está {embarque['estado']}.")
        filas = conn.execute(
            "SELECT t.id, u.codigo AS ubicacion FROM embarque_tarimas et "
            "JOIN tarimas t ON t.id = et.tarima_id LEFT JOIN ubicaciones u ON u.id = t.ubicacion_id "
            "WHERE et.embarque_id = ?", (embarque_id,)).fetchall()
        for fila in filas:
            conn.execute("UPDATE tarimas SET estado = 'despachada', ubicacion_id = NULL WHERE id = ?", (fila["id"],))
            _registrar_movimiento(conn, fila["id"], "despacho", fila["ubicacion"], embarque["sucursal"], operador)
        conn.execute("UPDATE embarques SET estado = 'despachado', fecha_salida = ? WHERE id = ?",
                     (_ahora(), embarque_id))
        agenda.completar_por_despacho(conn, embarque_id)
        return {"embarque_id": embarque_id, "estado": "despachado", "sucursal": embarque["sucursal"],
                "camion": embarque["placas"], "tarimas_despachadas": len(filas)}


def listar_embarques(estado=None):
    sql = ("SELECT e.id, e.estado, e.fecha_creacion, e.fecha_salida, s.nombre AS sucursal, c.placas, "
           "       (SELECT COUNT(*) FROM embarque_tarimas et WHERE et.embarque_id = e.id) AS tarimas "
           "FROM embarques e JOIN sucursales s ON s.id = e.sucursal_id "
           "LEFT JOIN camiones c ON c.id = e.camion_id")
    parametros = []
    if estado:
        sql += " WHERE e.estado = ?"
        parametros.append(estado)
    sql += " ORDER BY e.id DESC"
    with conexion() as conn:
        filas = [dict(f) for f in conn.execute(sql, parametros).fetchall()]
    for fila in filas:
        fila["codigo"] = codigo_embarque(fila["id"])
    return filas


def obtener_embarque(embarque_id):
    with conexion() as conn:
        embarque = dict(_embarque(conn, embarque_id))
        embarque["codigo"] = codigo_embarque(embarque_id)
        embarque["tarimas"] = [
            {"codigo": t["codigo"], "sku": t["sku"], "producto": t["producto"], "cantidad": t["cantidad"],
             "peso_kg": t["peso_kg"], "volumen_m3": t["volumen_m3"], "estado": t["estado"],
             "ubicacion": t["ubicacion"], "origen": t["origen"]}
            for t in _tarimas_embarque(conn, embarque_id)]
        embarque["peso_kg"] = round(sum(t["peso_kg"] for t in embarque["tarimas"]), 1)
        embarque["volumen_m3"] = round(sum(t["volumen_m3"] for t in embarque["tarimas"]), 2)
        # Bultos que viajan en el embarque (los que vienen de una OC), agrupados por tarima
        embarque["bultos"] = [dict(b) for b in conn.execute(
            "SELECT b.codigo, t.codigo AS tarima, oc.folio AS oc, oc.folio_factura AS factura, "
            "       pr.nombre AS proveedor, p.sku, p.nombre AS producto, b.piezas, b.peso_kg, b.volumen_m3 "
            "FROM bultos b JOIN tarimas t ON t.id = b.tarima_id "
            "JOIN embarque_tarimas et ON et.tarima_id = t.id "
            "JOIN ordenes_compra oc ON oc.id = b.oc_id JOIN proveedores pr ON pr.id = oc.proveedor_id "
            "JOIN productos p ON p.id = b.producto_id "
            "WHERE et.embarque_id = ? ORDER BY t.id, b.id", (embarque_id,)).fetchall()]
        camion = conn.execute(
            "SELECT c.placas, c.capacidad_kg, c.capacidad_m3 FROM embarques e JOIN camiones c ON c.id = e.camion_id "
            "WHERE e.id = ?", (embarque_id,)).fetchone()
        embarque["ocupacion"] = _ocupacion(_tarimas_embarque(conn, embarque_id), camion) if camion else None
        return embarque


def datos_etiquetas(recepcion_id=None, codigo=None):
    """Datos para imprimir etiquetas: las tarimas de una recepción o una sola tarima por su código."""
    if (recepcion_id is None) == (codigo is None):
        raise ValueError("Indica la recepción o el código de la tarima, no ambos.")
    filtro, valor = ("t.recepcion_id = ?", recepcion_id) if codigo is None else ("t.codigo = ?", codigo)
    with conexion() as conn:
        filas = conn.execute(
            "SELECT t.codigo, p.sku, p.nombre AS producto, t.cantidad, t.peso_kg, u.codigo AS ubicacion, "
            "       r.id AS recepcion_id, r.fecha_llegada, c.placas "
            "FROM tarimas t JOIN productos p ON p.id = t.producto_id "
            "JOIN recepciones r ON r.id = t.recepcion_id JOIN camiones c ON c.id = r.camion_id "
            "LEFT JOIN ubicaciones u ON u.id = t.ubicacion_id "
            f"WHERE {filtro} ORDER BY t.id", (valor,)).fetchall()
    if not filas:
        raise ErrorNegocio(f"No hay tarimas para {'la recepción ' + str(recepcion_id) if codigo is None else 'el código ' + codigo}.")
    return [dict(f) for f in filas]


# ------------------------------------------------- dashboard, plano, historial

def dashboard():
    with conexion() as conn:
        def contar(sql):
            return conn.execute(sql).fetchone()[0]

        total = contar("SELECT COUNT(*) FROM ubicaciones")
        ocupadas = contar("SELECT COUNT(*) FROM tarimas WHERE ubicacion_id IS NOT NULL")
        por_ubicar = contar("SELECT COUNT(*) FROM tarimas WHERE estado = 'recibida'")
        por_despachar = contar("SELECT COUNT(*) FROM embarques WHERE estado IN ('pendiente', 'validado')")
        return {
            "camiones_recibidos": contar("SELECT COUNT(*) FROM recepciones"),
            "embarques_realizados": contar("SELECT COUNT(*) FROM embarques WHERE estado = 'despachado'"),
            "tarimas_almacenadas": ocupadas,
            "capacidad_total": total,
            "capacidad_disponible": total - ocupadas,
            "ocupacion_pct": round(100 * ocupadas / total, 1) if total else 0,
            "movimientos_pendientes": {
                "tarimas_por_ubicar": por_ubicar,
                "embarques_por_despachar": por_despachar,
                "total": por_ubicar + por_despachar,
            },
        }


def mapa():
    """Datos del plano: cada rack con sus ubicaciones y lo que hay en ellas."""
    with conexion() as conn:
        filas = conn.execute(
            "SELECT r.codigo AS rack, r.niveles, r.posiciones, u.codigo AS ubicacion, u.nivel, u.posicion, "
            "       t.codigo AS tarima, p.sku, t.estado "
            "FROM ubicaciones u JOIN racks r ON r.id = u.rack_id "
            "LEFT JOIN tarimas t ON t.ubicacion_id = u.id "
            "LEFT JOIN productos p ON p.id = t.producto_id "
            "ORDER BY r.id, u.nivel, u.posicion").fetchall()
    racks = {}
    for f in filas:
        rack = racks.setdefault(f["rack"], {
            "rack": f["rack"], "niveles": f["niveles"], "posiciones": f["posiciones"],
            "total": 0, "ocupadas": 0, "ubicaciones": []})
        rack["total"] += 1
        if f["tarima"]:
            rack["ocupadas"] += 1
        rack["ubicaciones"].append({
            "codigo": f["ubicacion"], "nivel": f["nivel"], "posicion": f["posicion"],
            "tarima": f["tarima"], "sku": f["sku"], "estado": f["estado"]})
    return list(racks.values())


def listar_movimientos(limite=50):
    with conexion() as conn:
        filas = conn.execute(
            "SELECT m.id, m.fecha, t.codigo AS tarima, m.tipo, m.origen, m.destino, m.operador "
            "FROM movimientos m JOIN tarimas t ON t.id = m.tarima_id ORDER BY m.id DESC LIMIT ?",
            (limite,)).fetchall()
        return [dict(f) for f in filas]


# --------------------------------------------------------------------- demo

def _inventario_demo():
    """Carga unas recepciones de ejemplo para que el plano y el dashboard no arranquen vacíos."""
    # (placas, proveedor_id, tipo, [(sku, tarimas, cantidad por tarima, peso kg)])
    recepciones = [
        ("TRX-301-A", 1, "Papel y cuadernos", [("SKU-1001", 6, 48, 640), ("SKU-1002", 6, 60, 700), ("SKU-1003", 4, 60, 700)]),
        ("TRX-302-B", 2, "Oficina y folders", [("SKU-2001", 8, 120, 820), ("SKU-2002", 6, 100, 1000)]),
        ("TRX-303-C", 3, "Arte y mochilas", [("SKU-3001", 5, 80, 450), ("SKU-3002", 6, 60, 300)]),
        ("TRX-304-D", 1, "Papel y cuadernos", [("SKU-1004", 8, 50, 680), ("SKU-1001", 4, 48, 640)]),
    ]
    for placas, proveedor_id, tipo, lineas in recepciones:
        tarimas = [{"sku": sku, "cantidad": cantidad, "peso_kg": peso}
                   for sku, cuantas, cantidad, peso in lineas for _ in range(cuantas)]
        registrar_recepcion(placas, proveedor_id, tipo, tarimas, tipo_camion="Tráiler 53'",
                            capacidad_camion=26, operador="Demo")


def reiniciar(con_inventario=True):
    """Deja la base como nueva (útil antes de cada demostración)."""
    import ordenes  # aquí y no arriba: ordenes usa este módulo para registrar la recepción

    agenda.limpiar_google()  # quita de Google Calendar los eventos de las citas que se van a borrar
    database.reset_db()
    if con_inventario:
        _inventario_demo()
        agenda.datos_demo(ordenes.datos_demo())
    return dashboard()


# ------------------------------------------------------------ despliegue público

def verificar_clave_reinicio(clave):
    """Si CEDIS_CLAVE_REINICIO está definida, reiniciar la demo exige esa clave."""
    esperada = (os.environ.get("CEDIS_CLAVE_REINICIO") or "").strip()
    if esperada and (clave or "").strip() != esperada:
        raise ErrorNegocio("Clave de reinicio incorrecta.")


def reinicio_con_clave():
    return bool((os.environ.get("CEDIS_CLAVE_REINICIO") or "").strip())


def sembrar_si_vacia():
    """En un servidor nuevo (base vacía) carga la demostración para que el sistema no abra en blanco."""
    with database.conexion() as conn:
        hay = conn.execute("SELECT (SELECT COUNT(*) FROM tarimas) + (SELECT COUNT(*) FROM ordenes_compra)").fetchone()[0]
    if not hay:
        reiniciar(True)
        return True
    return False
