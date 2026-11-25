"""Pruebas de incidencias, sugerencias de carga, recepción en sucursal y reportes Excel. Uso: python3 test_extras.py"""
import io
import os
import tempfile

os.environ["CEDIS_DB"] = os.path.join(tempfile.mkdtemp(), "prueba.db")

import agenda  # noqa: E402
import control  # noqa: E402
import database  # noqa: E402
import ordenes  # noqa: E402
import reportes  # noqa: E402
import services  # noqa: E402
import sucursal  # noqa: E402
from comun import ErrorNegocio  # noqa: E402


def falla(texto, fn, *a, **k):
    try:
        fn(*a, **k)
    except ErrorNegocio as e:
        assert texto in str(e), (texto, str(e))
        return
    raise AssertionError("debió fallar: " + texto)


database.init_db()
services.reiniciar()

print("1. Descarga con rechazos alimenta los KPI de incidencias")
cita = [c for c in agenda.listar_citas() if c["oc_id"]][0]
pend = ordenes.estado_descarga(cita["id"])["pendientes"]
for p in pend[:30]:
    assert ordenes.escanear_bulto(cita["id"], p["codigo"])["aceptado"]
ordenes.escanear_bulto(cita["id"], pend[0]["codigo"])      # repetido
ordenes.escanear_bulto(cita["id"], "B-999999")             # no existe
ordenes.escanear_bulto(cita["id"], "B-999998")             # no existe
ordenes.cerrar_descarga(cita["id"], "TRX-401-A", True, True, True)  # quedan 5 sin escanear: OC parcial
k = control.resumen()
assert k["kpis"]["bultos_aceptados"] == 30 and k["kpis"]["bultos_rechazados"] == 3
assert k["kpis"]["exactitud_pct"] == round(100 * 30 / 33, 1) and k["kpis"]["ocs_parciales"] == 1
assert k["ocs_parciales"][0]["faltantes"] == 5
tipos = {t["tipo"]: t["total"] for t in k["por_tipo"]}
assert tipos == {"no_existe": 2, "repetido": 1}, tipos
assert k["kpis"]["descarga_promedio_seg"] is not None and len(k["lista"]) == 3 and k["lista"][0]["origen"] == "Descarga"

print("2. Sugerencias de carga y agregar tarimas")
e = services.crear_embarque(1, [{"sku": "SKU-1001", "tarimas": 2}])
s = services.sugerir_embarque(e["embarque_id"])
assert s["minimo_pct"] == 90 and len(s["camiones"]) >= 4
por = {c["placas"]: c for c in s["camiones"]}
assert por["VER-101-A"]["estado"] == "agregar" and por["VER-101-A"]["agregar"], por["VER-101-A"]
extra = por["VER-101-A"]["agregar"]
assert por["VER-101-A"]["peso_pct_final"] >= 90 or por["VER-101-A"]["volumen_pct_final"] >= 90
assert por["VER-104-D"]["estado"] in ("excede", "cumple", "agregar", "insuficiente")
try:
    services.validar_embarque(e["embarque_id"], "VER-101-A")
    raise AssertionError("debió rechazar el camión con poca carga")
except ErrorNegocio as ex:
    assert "no puede salir" in str(ex)
services.agregar_tarimas(e["embarque_id"], [t["codigo"] for t in extra])
v = services.validar_embarque(e["embarque_id"], "VER-101-A")   # con lo sugerido ya sale
assert v["ocupacion"]["cumple_minimo"]
falla("ya no admite", services.agregar_tarimas, e["embarque_id"], ["T-000001"])
e2 = services.crear_embarque(2, [{"sku": "SKU-2001", "tarimas": 1}])
falla("no existe", services.agregar_tarimas, e2["embarque_id"], ["T-999999"])
falla("no está disponible", services.agregar_tarimas, e2["embarque_id"], [extra[0]["codigo"]])
falla("pendiente", services.sugerir_embarque, e["embarque_id"])

print("3. Recepción en la sucursal")
falla("todavía no sale", sucursal.abrir, "E-%06d" % e2["embarque_id"])
falla("no es el QR de un embarque", sucursal.abrir, "T-000001")
falla("no existe", sucursal.abrir, "E-009999")
services.despachar_embarque(e["embarque_id"])
n = sucursal.abrir("e-%06d" % e["embarque_id"])
assert n["estado"] == "abierta" and n["esperados"] == len(services.obtener_embarque(e["embarque_id"])["tarimas"])
assert sucursal.abrir("E-%06d" % e["embarque_id"])["entrega_id"] == n["entrega_id"]  # retoma la misma
primero = n["pendientes"][0]["codigo"]
assert sucursal.escanear(n["entrega_id"], primero)["aceptado"]
r = sucursal.escanear(n["entrega_id"], primero)
assert not r["aceptado"] and "ya se escaneó" in r["motivo"]
r = sucursal.escanear(n["entrega_id"], "T-999999")
assert not r["aceptado"] and "no pertenece" in r["motivo"]
for p in n["pendientes"][1:-1]:
    assert sucursal.escanear(n["entrega_id"], p["codigo"])["aceptado"]
c = sucursal.cerrar(n["entrega_id"], "Una tarima llegó sin film")
assert c["recibidos"] == n["esperados"] - 1 and len(c["faltantes"]) == 1 and not c["completa"]
falla("ya fue cerrada", sucursal.escanear, n["entrega_id"], primero)
lista = sucursal.listar()
assert lista[0]["estado"] == "cerrada" and lista[0]["recibidos"] == n["esperados"] - 1

print("4. KPI final y Excel")
k = control.resumen()
assert k["kpis"]["entregas_con_faltantes"] == 1 and k["kpis"]["entregas_cerradas"] == 1
assert {"faltante_destino", "ajeno_destino", "repetido_destino"} <= {t["tipo"] for t in k["por_tipo"]}
assert any(f["origen"] == "Sucursal" and f["embarque"] for f in k["lista"])
try:
    from openpyxl import load_workbook
except ImportError:
    print("   (omitido: falta openpyxl)")
else:
    wb = load_workbook(io.BytesIO(reportes.construir("completo")))
    assert wb.sheetnames == ["Inventario", "Movimientos", "Órdenes de compra", "Bultos", "Embarques", "Agenda", "Incidencias", "Recepciones"]
    assert wb["Inventario"].max_row > 40 and wb["Incidencias"].max_row == 1 + len(control.resumen()["lista"])
    assert wb["Inventario"]["A1"].value == "Tarima"
    assert load_workbook(io.BytesIO(reportes.construir("ordenes"))).sheetnames == ["Órdenes de compra", "Bultos"]
    falla("No existe el reporte", reportes.construir, "nada")
print("5. Despliegue público: siembra y clave de reinicio")
import os
os.environ.pop("CEDIS_CLAVE_REINICIO", None)
services.verificar_clave_reinicio("")  # sin clave configurada, no se exige
assert services.reinicio_con_clave() is False
os.environ["CEDIS_CLAVE_REINICIO"] = "manati"
assert services.reinicio_con_clave() is True
falla("Clave de reinicio incorrecta", services.verificar_clave_reinicio, "mala")
falla("Clave de reinicio incorrecta", services.verificar_clave_reinicio, "")
services.verificar_clave_reinicio("manati")
os.environ.pop("CEDIS_CLAVE_REINICIO")
services.reiniciar(False)
assert services.sembrar_si_vacia() is True and services.sembrar_si_vacia() is False
print("\nTodas las pruebas extra pasaron.")
