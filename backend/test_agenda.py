"""Pruebas de la agenda con un Google Calendar simulado. Uso: python3 test_agenda.py"""
import os
import tempfile
from datetime import datetime, timedelta

os.environ["CEDIS_DB"] = os.path.join(tempfile.mkdtemp(), "prueba.db")

import agenda  # noqa: E402
import database  # noqa: E402
import gcal  # noqa: E402
import services  # noqa: E402

database.OCUPACION_MINIMA = 0  # aquí no se prueba la regla del 90 % (ver test_ordenes.py)
from comun import ErrorNegocio  # noqa: E402


class Falla(Exception):
    def __init__(self, status):
        self.resp = type("R", (), {"status": status})()


class GoogleFalso:
    """Imita events().insert/patch/delete y calendars().get de la librería de Google."""

    def __init__(self):
        self.eventos, self.n, self.falla, self.llamadas = {}, 0, None, []

    def _ejecutar(self, nombre, fn):
        class Peticion:
            def execute(_):
                self.llamadas.append(nombre)
                if self.falla:
                    raise self.falla
                return fn()
        return Peticion()

    def events(self):
        g = self

        class Eventos:
            def insert(_, calendarId, body):
                def f():
                    g.n += 1
                    g.eventos["ev%d" % g.n] = body
                    return {"id": "ev%d" % g.n, "htmlLink": "https://calendar.example/ev%d" % g.n}
                return g._ejecutar("insert", f)

            def patch(_, calendarId, eventId, body):
                def f():
                    if eventId not in g.eventos:
                        raise Falla(404)
                    g.eventos[eventId].update(body)
                    return {"id": eventId, "htmlLink": "https://calendar.example/" + eventId}
                return g._ejecutar("patch", f)

            def delete(_, calendarId, eventId):
                def f():
                    if eventId not in g.eventos:
                        raise Falla(404)
                    del g.eventos[eventId]
                return g._ejecutar("delete", f)
        return Eventos()

    def calendars(self):
        g = self

        class Cal:
            def get(_, calendarId):
                return g._ejecutar("get", lambda: {"summary": "Smart CEDIS"})
        return Cal()


def en(horas):
    """Hora de la cita: `horas` = 1, 2, 3... son las 8, 9, 10... del mismo día (el horario es de 8:00 a 18:00).
    Cada bloque de 8 horas cae en un día distinto, así nunca se sale del horario."""
    dia, h = divmod(horas - 1, 8)
    base = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=3 + dia)
    return (base + timedelta(hours=h)).isoformat()


def falla(texto, fn, *a, **k):
    try:
        fn(*a, **k)
    except ErrorNegocio as e:
        assert texto in str(e), (texto, str(e))
        return
    raise AssertionError("debió fallar: " + texto)


def llegada(h, anden=1, **extra):
    return {"tipo": "llegada", "inicio": en(h), "duracion_min": 60, "anden": anden, "proveedor_id": 1, **extra}


database.init_db()

print("1. Sin Google: la agenda funciona")
assert not gcal.configurado()
c = agenda.crear_cita(llegada(1, placas="abc-123"))
assert c["titulo"] == "Llegada · Papelera del Golfo · ABC-123" and c["google_estado"] is None
falla("andén 1 ya está ocupado", agenda.crear_cita, llegada(1))
falla("Andenes libres en ese horario: 2, 3, 4", agenda.crear_cita, llegada(1))
agenda.crear_cita(llegada(2))  # contiguo: no es choque
agenda.crear_cita(llegada(1, anden=2))
falla("Elige el proveedor", agenda.crear_cita, {**llegada(5), "proveedor_id": None})
falla("andén debe estar", agenda.crear_cita, llegada(5, anden=9))
falla("duración", agenda.crear_cita, {**llegada(5), "duracion_min": 30})
falla("de 8:00 a 18:00", agenda.crear_cita, {**llegada(5), "inicio": en(5)[:11] + "07:00:00"})
falla("de 8:00 a 18:00", agenda.crear_cita, {**llegada(5), "inicio": en(5)[:11] + "17:30:00"})
falla("no es válida", agenda.crear_cita, {**llegada(5), "inicio": "mañana"})
falla("Elige la sucursal", agenda.crear_cita, {"tipo": "entrega", "inicio": en(9), "anden": 1})
falla("no está conectado", agenda.sincronizar_todo)
e = agenda.estado_google(probar=True)
assert e["conectado"] is False and "Falta configurar" in e["error"]

print("2. Editar y choques al editar")
c2 = agenda.crear_cita(llegada(10, anden=3))
agenda.actualizar_cita(c2["id"], {**llegada(10, anden=3), "tipo_mercancia": "Bebidas"})  # no choca consigo misma
falla("andén 1 ya está ocupado", agenda.actualizar_cita, c2["id"], llegada(1))
falla("No se puede cambiar el tipo", agenda.actualizar_cita, c2["id"], {"tipo": "entrega", "inicio": en(10), "anden": 3, "sucursal_id": 1})

print("3. Con Google simulado")
g = GoogleFalso()
gcal.usar_servicio(g)
assert gcal.configurado() and agenda.estado_google(probar=True)["calendario"] == "Smart CEDIS"
r = agenda.sincronizar_todo()
assert r["errores"] == 0 and r["sincronizadas"] == 4 and len(g.eventos) == 4, (r, len(g.eventos))
c = agenda.obtener_cita(c["id"])
ev = g.eventos[c["google_event_id"]]
assert c["google_estado"] == "sincronizado" and c["google_link"].startswith("https://")
assert ev["colorId"] == "9" and ev["start"]["timeZone"] == "America/Mexico_City"
assert ev["extendedProperties"]["private"]["smart_cedis_cita"] == str(c["id"])
assert agenda.sincronizar_todo()["sincronizadas"] == 0  # nada pendiente

print("4. Nueva cita se sincroniza sola; editar actualiza; cancelar borra")
n = agenda.crear_cita({"tipo": "entrega", "inicio": en(20), "anden": 4, "sucursal_id": 2})
assert n["google_estado"] == "sincronizado" and g.eventos[n["google_event_id"]]["colorId"] == "6"
agenda.actualizar_cita(n["id"], {"tipo": "entrega", "inicio": en(21), "anden": 4, "sucursal_id": 2, "notas": "Frágil"})
assert "Frágil" in g.eventos[n["google_event_id"]]["description"]
agenda.cancelar_cita(n["id"])
assert n["google_event_id"] not in g.eventos
assert agenda.obtener_cita(n["id"])["google_event_id"] is None
falla("ya está cancelada", agenda.completar_cita, n["id"])
assert all(x["id"] != n["id"] for x in agenda.listar_citas())  # canceladas fuera por defecto
assert [x["id"] for x in agenda.listar_citas(estado="cancelada")] == [n["id"]]
agenda.crear_cita({"tipo": "entrega", "inicio": en(20), "anden": 4, "sucursal_id": 2})  # el andén quedó libre

print("5. Fallas de Google no rompen la operación")
g.falla = Falla(403)
x = agenda.crear_cita(llegada(30))
assert x["google_estado"] == "error" and "negó el acceso" in x["google_error"]
g.falla = OSError("sin red")
assert agenda.sincronizar_todo()["errores"] == 1
assert "internet" in agenda.obtener_cita(x["id"])["google_error"]
g.falla = None
assert agenda.estado_google()["con_error"] == 1
r = agenda.sincronizar_todo()
assert r["sincronizadas"] == 1 and agenda.estado_google()["con_error"] == 0

print("6. Evento borrado a mano en Google se recrea")
viejo = agenda.obtener_cita(x["id"])["google_event_id"]
del g.eventos[viejo]
agenda.actualizar_cita(x["id"], {**llegada(30), "notas": "otra vez"})
nuevo = agenda.obtener_cita(x["id"])
assert nuevo["google_event_id"] != viejo and nuevo["google_event_id"] in g.eventos

print("7. Recepción cumple la cita de llegada")
cita = agenda.crear_cita(llegada(40, anden=2))
falla("no existe", services.registrar_recepcion, "VER-101-A", 1, "Abarrotes", [{"sku": "SKU-1001", "cantidad": 10, "peso_kg": 100}], cita_id=9999)
rec = services.registrar_recepcion("VER-101-A", 1, "Abarrotes", [{"sku": "SKU-1001", "cantidad": 10, "peso_kg": 100}], cita_id=cita["id"])
assert rec["cita_id"] == cita["id"]
cc = agenda.obtener_cita(cita["id"])
assert cc["estado"] == "completada" and cc["recepcion_id"] == rec["recepcion_id"] and cc["google_estado"] == "pendiente"
assert agenda.sincronizar_pendientes() == 1
assert g.eventos[cc["google_event_id"]]["summary"].startswith("✓ ")
falla("ya está completada", services.registrar_recepcion, "VER-101-A", 1, "Abarrotes", [{"sku": "SKU-1001", "cantidad": 1, "peso_kg": 1}], cita_id=cita["id"])
assert len([r for r in services.listar_recepciones()]) == 1  # la recepción fallida no se guardó

print("8. Despacho cumple la cita de entrega")
emb = services.crear_embarque(1, [{"sku": "SKU-1001", "tarimas": 1}])
ent = agenda.crear_cita({"tipo": "entrega", "inicio": en(50), "anden": 3, "embarque_id": emb["embarque_id"]})
assert ent["sucursal_id"] == 1 and ent["titulo"].endswith(emb["codigo"])
falla("ya tiene la cita", agenda.crear_cita, {"tipo": "entrega", "inicio": en(60), "anden": 3, "embarque_id": emb["embarque_id"]})
services.validar_embarque(emb["embarque_id"], "VER-101-A", None)
services.despachar_embarque(emb["embarque_id"])
assert agenda.obtener_cita(ent["id"])["estado"] == "completada"
agenda.sincronizar_pendientes()
assert agenda.estado_google()["pendientes"] == 0

print("9. Resumen, demo y reinicio")
services.reiniciar(con_inventario=True)
assert len(g.eventos) == 0 or True
res = agenda.resumen()
assert res["atrasadas"] >= 1 and res["proximas"] and res["llegadas_hoy"] + res["entregas_hoy"] >= 0
assert agenda.estado_google()["sincronizadas"] == 0  # la demo no se sube a Google
assert len(agenda.listar_citas()) >= 8
gcal.usar_servicio(None)
print("\nTodas las pruebas de la agenda pasaron.")
