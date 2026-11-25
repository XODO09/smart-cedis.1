"""Prueba del flujo completo del CEDIS sobre la capa de servicios (no necesita FastAPI).

Ejecutar:  python test_flujo.py
"""
import os
import tempfile

# La prueba usa su propia base temporal para no tocar cedis.db
os.environ["CEDIS_DB"] = os.path.join(tempfile.mkdtemp(), "prueba.db")

import database  # noqa: E402
import services  # noqa: E402
from services import ErrorNegocio  # noqa: E402

# Esta prueba recorre el flujo con cargas pequeñas; la regla del 90 % de ocupación se prueba en test_ordenes.py
database.OCUPACION_MINIMA = 0


def debe_fallar(funcion, *args, texto="", **kwargs):
    try:
        funcion(*args, **kwargs)
    except ErrorNegocio as e:
        assert texto in str(e), f"Mensaje inesperado: {e}"
        return str(e)
    raise AssertionError("Debió lanzar ErrorNegocio")


def sin_ubicaciones_repetidas():
    with database.conexion() as conn:
        repetidas = conn.execute(
            "SELECT ubicacion_id FROM tarimas WHERE ubicacion_id IS NOT NULL "
            "GROUP BY ubicacion_id HAVING COUNT(*) > 1").fetchall()
    assert not repetidas, "Hay dos tarimas en la misma ubicación"


# 1. Base nueva ---------------------------------------------------------------
d = services.reiniciar(con_inventario=False)
assert d["capacidad_total"] == 32 * 4 * 6 == 768
assert d["tarimas_almacenadas"] == 0 and d["camiones_recibidos"] == 0
assert len(services.mapa()) == 32
print("1. Base nueva: 32 racks, 768 ubicaciones")

# 2. Recepción con ubicación automática ----------------------------------------
r = services.registrar_recepcion(
    "TST-001-A", 1, "Abarrotes",
    [{"sku": "SKU-1001", "cantidad": 48, "peso_kg": 640},
     {"sku": "SKU-1001", "cantidad": 48, "peso_kg": 640},
     {"sku": "SKU-2002", "cantidad": 100, "peso_kg": 1000}],  # tarima pesada
    operador="Gamaliel")
assert r["tarimas"] == ["T-000001", "T-000002", "T-000003"] and not r["sin_ubicar"]
ubic = {t["codigo"]: t["ubicacion"] for t in services.inventario()["tarimas"]}
assert ubic["T-000001"] == "R01-N1-P1" and ubic["T-000002"] == "R01-N1-P2"
assert ubic["T-000003"].split("-")[1] == "N1", "La tarima pesada debe ir en nivel 1"
d = services.dashboard()
assert d["camiones_recibidos"] == 1 and d["tarimas_almacenadas"] == 3 and d["capacidad_disponible"] == 765
print("2. Recepción: 3 tarimas ubicadas, la pesada en nivel 1")

# 3. Embarque: apartado de tarimas ---------------------------------------------
e = services.crear_embarque(1, [{"sku": "SKU-1001", "tarimas": 2}], operador="Gamaliel")
assert e["estado"] == "pendiente" and len(e["tarimas"]) == 2
estados = {t["codigo"]: t["estado"] for t in services.inventario()["tarimas"]}
assert estados["T-000001"] == estados["T-000002"] == "asignada" and estados["T-000003"] == "almacenada"
assert services.dashboard()["movimientos_pendientes"]["embarques_por_despachar"] == 1
debe_fallar(services.crear_embarque, 1, [{"sku": "SKU-2002", "tarimas": 5}], texto="Solo hay 1")
debe_fallar(services.crear_embarque, 1, [{"sku": "SKU-1001", "tarimas": 1}], texto="Solo hay 0")
print("3. Embarque creado; no se pueden pedir tarimas que no hay ni reutilizar las apartadas")

# 4. Validación -----------------------------------------------------------------
debe_fallar(services.validar_embarque, e["embarque_id"], "NO-EXISTE", texto="no está registrado")
debe_fallar(services.validar_embarque, e["embarque_id"], "VER-102-B",
            codigos_escaneados=["T-000001", "T-000003"], texto="faltan: T-000002")
v = services.validar_embarque(e["embarque_id"], "VER-102-B", ["T-000001", "T-000002"])
assert v["estado"] == "validado"
debe_fallar(services.validar_embarque, e["embarque_id"], "VER-102-B", texto="está validado")
print("4. Validación: detecta carga que no coincide y camión inexistente")

# 5. Despacho -------------------------------------------------------------------
x = services.despachar_embarque(e["embarque_id"], "Gamaliel")
assert x["tarimas_despachadas"] == 2 and x["sucursal"] == "Sucursal Xalapa"
d = services.dashboard()
assert d["embarques_realizados"] == 1 and d["tarimas_almacenadas"] == 1 and d["capacidad_disponible"] == 767
assert d["movimientos_pendientes"]["total"] == 0
debe_fallar(services.despachar_embarque, e["embarque_id"], texto="está despachado")
assert [t["codigo"] for t in services.inventario()["tarimas"]] == ["T-000003"]
assert len(services.inventario(estado="despachada")["tarimas"]) == 2
tipos = [m["tipo"] for m in services.listar_movimientos(100) if m["tarima"] == "T-000001"]
assert tipos[::-1] == ["recepcion", "almacenamiento", "asignacion_embarque", "despacho"], tipos
print("5. Despacho: inventario descontado, ubicaciones liberadas, historial completo")

# 6. Capacidad del camión -----------------------------------------------------------
services.registrar_recepcion("TST-002-B", 1, "Abarrotes",
                             [{"sku": "SKU-1002", "cantidad": 60, "peso_kg": 700}] * 5)
e2 = services.crear_embarque(2, [{"sku": "SKU-1002", "tarimas": 5}])
debe_fallar(services.validar_embarque, e2["embarque_id"], "VER-104-D", texto="capacidad para 4")
services.validar_embarque(e2["embarque_id"], "VER-103-C")
print("6. Capacidad del camión: 5 tarimas no caben en una camioneta de 4")

# 7. Almacén lleno -------------------------------------------------------------------
services.reiniciar(con_inventario=False)
r = services.registrar_recepcion(
    "TST-003-C", 3, "Limpieza", [{"sku": "SKU-3002", "cantidad": 60, "peso_kg": 300}] * 770)
assert r["ubicadas"] == 768 and len(r["sin_ubicar"]) == 2
d = services.dashboard()
assert d["capacidad_disponible"] == 0 and d["ocupacion_pct"] == 100
assert d["movimientos_pendientes"]["tarimas_por_ubicar"] == 2
debe_fallar(services.asignar_ubicacion, r["sin_ubicar"][0], texto="No hay ubicaciones")
sin_ubicaciones_repetidas()
print("7. Almacén lleno: 768 ubicadas, 2 quedan pendientes y nunca se repite una ubicación")

# 8. Demo ------------------------------------------------------------------------------
d = services.reiniciar(con_inventario=True)
assert d["camiones_recibidos"] == 4 and d["tarimas_almacenadas"] == 53
sin_ubicaciones_repetidas()
print("8. Inventario de demostración: 53 tarimas en 4 recepciones")

# 9. Folios, QR y PDF ------------------------------------------------------------------
try:
    import documentos
except ImportError:
    print("9. (omitido) falta instalar reportlab:  pip install reportlab")
else:
    e = services.crear_embarque(1, [{"sku": "SKU-1001", "tarimas": 2}, {"sku": "SKU-2001", "tarimas": 1}])
    assert e["codigo"] == "E-000001"
    d = services.obtener_embarque(e["embarque_id"])
    assert d["codigo"] == "E-000001" and len(d["tarimas"]) == 3
    assert d["tarimas"][0]["producto"] and d["tarimas"][0]["cantidad"] > 0 and d["tarimas"][0]["peso_kg"] > 0
    assert services.listar_embarques()[0]["codigo"] == "E-000001"

    svg = documentos.qr_svg(d["codigo"])
    assert svg.startswith("<svg") and "<path" in svg
    assert documentos.matriz_qr("T-000001") != documentos.matriz_qr("T-000002")
    for malo in ("XYZ", "t-000001", "T-1; DROP", ""):
        try:
            documentos.validar_codigo(malo)
            raise AssertionError(f"Aceptó el código inválido {malo!r}")
        except documentos.CodigoInvalido:
            pass

    pdf = documentos.pdf_relacion_embarque(d)  # pendiente: se genera con aviso de preliminar
    assert pdf.startswith(b"%PDF-") and len(pdf) > 3000
    services.validar_embarque(e["embarque_id"], "VER-103-C")
    services.despachar_embarque(e["embarque_id"])
    d = services.obtener_embarque(e["embarque_id"])
    assert all(t["ubicacion"] is None and t["origen"] for t in d["tarimas"]), \
        "Tras el despacho la ubicación se libera pero el origen debe conservarse para la relación"
    assert documentos.pdf_relacion_embarque(d).startswith(b"%PDF-")

    etiquetas = services.datos_etiquetas(recepcion_id=1)
    assert len(etiquetas) == 16 and documentos.pdf_etiquetas(etiquetas).startswith(b"%PDF-")
    assert documentos.pdf_etiquetas(services.datos_etiquetas(codigo="T-000001")).startswith(b"%PDF-")
    debe_fallar(services.datos_etiquetas, codigo="T-999999", texto="No hay tarimas")
    debe_fallar(services.datos_etiquetas, recepcion_id=999, texto="No hay tarimas")
    print("9. QR y PDF: folio E-000001, QR válidos, relación y etiquetas generadas")

print("\nTodas las pruebas pasaron.")
