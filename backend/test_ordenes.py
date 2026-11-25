"""Pruebas de las reglas de OC, bultos, descarga con terminal portátil y salida del camión. Uso: python3 test_ordenes.py"""
import os
import tempfile
from datetime import datetime, timedelta

os.environ["CEDIS_DB"] = os.path.join(tempfile.mkdtemp(), "prueba.db")

import agenda  # noqa: E402
import database  # noqa: E402
import ordenes  # noqa: E402
import services  # noqa: E402
from comun import ErrorNegocio  # noqa: E402


def falla(texto, fn, *a, **k):
    try:
        fn(*a, **k)
    except ErrorNegocio as e:
        assert texto in str(e), (texto, str(e))
        return
    raise AssertionError("debió fallar: " + texto)


def linea(**k):
    return {"sku": "SKU-1001", "bultos": 4, "piezas_por_bulto": 12, "peso_kg": 15, "volumen_m3": 0.05, **k}


def orden(folio="OC-1", factura="F-1", **k):
    return {"folio": folio, "folio_factura": factura, "proveedor_id": 1, "sucursal_id": 1, "lineas": [linea()], **k}


def cita(oc_id, hora=9, anden=1, dias=1):
    d = datetime.now().replace(hour=hora, minute=0, second=0, microsecond=0) + timedelta(days=dias)
    return agenda.crear_cita({"tipo": "llegada", "inicio": d.isoformat(), "duracion_min": 60, "anden": anden,
                              "oc_id": oc_id, "placas": "TRX-1"}, sincronizar=False)


database.init_db()

print("1. OC: factura única y desglose por bulto")
o = ordenes.crear_orden(orden())
assert o["bultos"] == 4 and o["lineas"][0]["facturadas"] == 48 and o["estado"] == "pendiente"
falla("ya está relacionado con la OC OC-1", ordenes.crear_orden, orden("OC-2", " f-1 "))  # sin importar mayúsculas ni espacios
falla("Ya existe una OC", ordenes.crear_orden, orden("OC-1", "F-9"))
falla("no solicitada", ordenes.crear_orden, orden("OC-3", "F-3", lineas=[linea(piezas_solicitadas=40)]))
falla("dos líneas", ordenes.crear_orden, orden("OC-3", "F-3", lineas=[linea(), linea()]))
falla("Escribe el folio de la factura", ordenes.crear_orden, orden("OC-3", "  "))
falla("mayor a cero", ordenes.crear_orden, orden("OC-3", "F-3", lineas=[linea(peso_kg=0)]))
assert len(ordenes.listar_ordenes()) == 1  # los intentos fallidos no dejaron nada a medias
bultos = ordenes.datos_etiquetas_bultos(oc_id=o["id"])
assert [b["codigo"] for b in bultos] == ["B-000001", "B-000002", "B-000003", "B-000004"]
assert bultos[0]["qr"] == "B-000001|OC-1|PRV1|SUC1|SKU-1001|12"

print("2. Agenda: horario 8-18, mínimo 1 h y OC ligada")
c = cita(o["id"])
assert c["oc_folio"] == "OC-1" and c["proveedor_id"] == 1 and "OC-1" in c["titulo"]
falla("ya tiene la cita", cita, o["id"], hora=11, anden=2)
o2 = ordenes.crear_orden(orden("OC-2", "F-2", proveedor_id=2))
c2 = cita(o2["id"], hora=11, anden=2, dias=2)
assert c2["proveedor_id"] == 2  # el proveedor lo define la OC aunque se mande otro
falla("de 8:00 a 18:00", agenda.crear_cita, {"tipo": "llegada", "inicio": (datetime.now() + timedelta(days=1)).replace(hour=17, minute=30).isoformat(), "duracion_min": 60, "anden": 3, "proveedor_id": 1})
falla("entre 60", agenda.crear_cita, {"tipo": "llegada", "inicio": (datetime.now() + timedelta(days=1)).replace(hour=12, minute=0).isoformat(), "duracion_min": 45, "anden": 3, "proveedor_id": 1})

print("3. Descarga: escaneo y rechazo de lo no solicitado")
e = ordenes.estado_descarga(c["id"])
assert e["esperados"] == 4 and e["escaneados"] == 0
r = ordenes.escanear_bulto(c["id"], "B-000001")
assert r["aceptado"] and r["progreso"]["escaneados"] == 1
r = ordenes.escanear_bulto(c["id"], "b-000002|OC-1|PRV1|SUC1|SKU-1001|12")  # el QR completo y en minúsculas
assert r["aceptado"]
for lectura, texto in [("B-000001", "ya fue escaneado"), ("B-999999", "no existe en el sistema"),
                       ("B-000003|OC-1|PRV1|SUC1|SKU-2001|12", "no coinciden"), ("hola", "no existe"),
                       (ordenes.datos_etiquetas_bultos(oc_id=o2["id"])[0]["codigo"], "pertenece a la OC OC-2")]:
    r = ordenes.escanear_bulto(c["id"], lectura)
    assert not r["aceptado"] and texto in r["motivo"], (lectura, r["motivo"])
inc = ordenes.estado_descarga(c["id"])["incidencias"]
assert len(inc) == 5 and ordenes.estado_descarga(c["id"])["escaneados"] == 2  # lo rechazado no cuenta como recibido
sin_oc = agenda.crear_cita({"tipo": "llegada", "inicio": (datetime.now() + timedelta(days=4)).replace(hour=9, minute=0).isoformat(), "duracion_min": 60, "anden": 1, "proveedor_id": 1}, sincronizar=False)
falla("no tiene una OC ligada", ordenes.estado_descarga, sin_oc["id"])

print("4. Cerrar descarga: checklist, tarimas por OC y recepción parcial")
falla("film de seguridad", ordenes.cerrar_descarga, c["id"], "TRX-1", True, False, True)
falla("placas", ordenes.cerrar_descarga, c["id"], " ", True, True, True)
r = ordenes.cerrar_descarga(c["id"], "trx-1", True, True, True)
assert r["bultos_recibidos"] == 2 and r["bultos_faltantes"] == 2 and r["estado_oc"] == "parcial" and r["rechazos"] == 5
assert agenda.obtener_cita(c["id"])["estado"] == "completada"
inv = services.inventario()["tarimas"]
assert len(inv) == 1 and inv[0]["ubicacion"]
with database.conexion() as conn:
    t = conn.execute("SELECT * FROM tarimas").fetchone()
    assert t["sucursal_id"] == 1 and t["oc_id"] == o["id"] and t["cantidad"] == 24 and abs(t["peso_kg"] - 30) < 1e-9
    assert conn.execute("SELECT COUNT(*) FROM bultos WHERE estado = 'recibido' AND tarima_id = ?", (t["id"],)).fetchone()[0] == 2
falla("ya está completada", ordenes.estado_descarga, c["id"])

print("5. Tarimas de un solo producto y con tope de peso")
big = ordenes.crear_orden(orden("OC-5", "F-5", lineas=[linea(sku="SKU-1001", bultos=30, peso_kg=40, volumen_m3=0.05),
                                                       linea(sku="SKU-1002", bultos=3, peso_kg=20, volumen_m3=0.05)]))
cb = cita(big["id"], hora=14, anden=3, dias=3)
for b in ordenes.estado_descarga(cb["id"])["pendientes"]:
    assert ordenes.escanear_bulto(cb["id"], b["codigo"])["aceptado"]
r = ordenes.cerrar_descarga(cb["id"], "TRX-2", True, True, True)
assert r["estado_oc"] == "recibida" and r["bultos_faltantes"] == 0
with database.conexion() as conn:
    filas = conn.execute("SELECT p.sku, t.peso_kg, t.cantidad FROM tarimas t JOIN productos p ON p.id = t.producto_id WHERE t.oc_id = ? ORDER BY t.id", (big["id"],)).fetchall()
assert [f["sku"] for f in filas] == ["SKU-1001", "SKU-1001", "SKU-1002"], [tuple(f) for f in filas]
assert all(f["peso_kg"] <= ordenes.TARIMA_MAX_KG for f in filas) and sum(f["cantidad"] for f in filas) == 30 * 12 + 3 * 12

print("6. Embarques: solo salen tarimas de su sucursal y con el 90% del camión")
falla("Solo hay 0", services.crear_embarque, 2, [{"sku": "SKU-1001", "tarimas": 1}])  # esa mercancía es para la sucursal 1
emb = services.crear_embarque(1, [{"sku": "SKU-1001", "tarimas": 2}])
d = services.obtener_embarque(emb["embarque_id"])
assert d["peso_kg"] > 0 and d["volumen_m3"] > 0 and len(d["bultos"]) == 27 and d["bultos"][0]["oc"] in ("OC-1", "OC-5")
mensaje = None
try:
    services.validar_embarque(emb["embarque_id"], "VER-103-C")
except ErrorNegocio as ex:
    mensaje = str(ex)
assert mensaje and "no puede salir" in mensaje and "90%" in mensaje, mensaje

# Criterio "cualquiera": basta el 90 % en peso o en volumen; "ambos": exige los dos
with database.conexion() as conn:
    conn.execute("UPDATE camiones SET capacidad_kg = ?, capacidad_m3 = 1000 WHERE placas = 'VER-103-C'", (d["peso_kg"] / 0.95,))
v = services.validar_embarque(emb["embarque_id"], "VER-103-C")
assert v["ocupacion"]["cumple_minimo"] and 94 < v["ocupacion"]["peso_pct"] < 96 and v["ocupacion"]["volumen_pct"] < 10
emb2 = services.crear_embarque(1, [{"sku": "SKU-1002", "tarimas": 1}])
database.CRITERIO_OCUPACION = "ambos"
with database.conexion() as conn:
    conn.execute("UPDATE camiones SET capacidad_kg = 30, capacidad_m3 = 1000 WHERE placas = 'VER-102-B'")
falla("excede la capacidad", services.validar_embarque, emb2["embarque_id"], "VER-102-B")
with database.conexion() as conn:
    p = conn.execute("SELECT peso_kg, volumen_m3 FROM tarimas WHERE id = (SELECT tarima_id FROM embarque_tarimas WHERE embarque_id = ?)", (emb2["embarque_id"],)).fetchone()
    conn.execute("UPDATE camiones SET capacidad_kg = ?, capacidad_m3 = 1000 WHERE placas = 'VER-102-B'", (p["peso_kg"],))
falla("no puede salir", services.validar_embarque, emb2["embarque_id"], "VER-102-B")  # 100 % en peso pero ~0 % en volumen
database.CRITERIO_OCUPACION = "cualquiera"
assert services.validar_embarque(emb2["embarque_id"], "VER-102-B")["ocupacion"]["cumple_minimo"]

print("7. PDF: etiquetas con QR legible y relación con bultos")
try:
    import documentos
    import cv2
    import numpy as np
    from pdf2image import convert_from_bytes  # noqa: F401
except ImportError:
    print("   (omitido: faltan reportlab, opencv o pdf2image para decodificar los QR)")
else:
    pdf = documentos.pdf_etiquetas_bultos(ordenes.datos_etiquetas_bultos(oc_id=o["id"]))
    paginas = convert_from_bytes(pdf, dpi=200)
    assert len(paginas) == 4
    lector = cv2.QRCodeDetector()
    leido, *_ = lector.detectAndDecode(cv2.cvtColor(np.array(paginas[0]), cv2.COLOR_RGB2BGR))
    assert leido == "B-000001|OC-1|PRV1|SUC1|SKU-1001|12", leido
    rel = documentos.pdf_relacion_embarque(services.obtener_embarque(emb["embarque_id"]))
    assert rel.startswith(b"%PDF-")
print("\nTodas las pruebas de órdenes pasaron.")
