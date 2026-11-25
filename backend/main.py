import os
"""API de Smart CEDIS. Arranque: uvicorn main:app --reload  (documentación en /docs)."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import agenda
import control
import database
import documentos
import ordenes
import reportes
import services
import sucursal
from services import ErrorNegocio


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    if os.environ.get("CEDIS_SEMBRAR_DEMO"):
        services.sembrar_si_vacia()
    yield


app = FastAPI(title="Smart CEDIS API", version="0.1.0", lifespan=lifespan)

# Permite que el frontend de React (Vite usa 5173) consuma la API en desarrollo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ErrorNegocio)
async def manejar_error_negocio(request, exc: ErrorNegocio):
    return JSONResponse(status_code=400, content={"detalle": str(exc)})


@app.exception_handler(Exception)
async def manejar_error_inesperado(request, exc: Exception):
    """Cualquier fallo no previsto responde en JSON con un mensaje claro (no un texto suelto del servidor)."""
    return JSONResponse(status_code=500, content={"detalle": "Ocurrió un error inesperado en el servidor. "
                                                  "Intenta de nuevo; si se repite, revisa la Terminal donde corre el sistema."})


@app.exception_handler(documentos.CodigoInvalido)
async def manejar_codigo_invalido(request, exc):
    return JSONResponse(status_code=400, content={"detalle": str(exc)})


def _pdf(contenido: bytes, nombre: str) -> Response:
    """PDF que el navegador abre en una pestaña (desde ahí se imprime o se guarda)."""
    return Response(content=contenido, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{nombre}"'})


# ------------------------------------------------------------------ modelos

class TarimaIn(BaseModel):
    sku: str
    cantidad: int = Field(gt=0)
    peso_kg: float = Field(gt=0)


class RecepcionIn(BaseModel):
    placas: str
    proveedor_id: int
    tipo_mercancia: str
    tarimas: List[TarimaIn] = Field(min_length=1)
    # Solo se usan si las placas del camión aún no están registradas
    tipo_camion: str = "Torton"
    capacidad_camion: int = Field(default=14, gt=0)
    ubicar_automaticamente: bool = True
    operador: str = "operador"
    cita_id: Optional[int] = None  # cita de llegada que se cumple con esta recepción


class ItemEmbarque(BaseModel):
    sku: str
    tarimas: int = Field(gt=0)


class EmbarqueIn(BaseModel):
    sucursal_id: int
    items: List[ItemEmbarque] = Field(min_length=1)
    operador: str = "operador"


class ValidacionIn(BaseModel):
    placas_camion: str
    codigos_escaneados: Optional[List[str]] = None


class OperadorIn(BaseModel):
    operador: str = "operador"


class CitaIn(BaseModel):
    tipo: str = Field(pattern="^(llegada|entrega)$")
    inicio: str                                   # hora local ISO: 2026-11-26T10:00
    duracion_min: int = Field(default=60, ge=agenda.DURACION_MIN, le=agenda.DURACION_MAX)
    anden: int = Field(ge=1, le=database.NUM_ANDENES)
    proveedor_id: Optional[int] = None
    sucursal_id: Optional[int] = None
    embarque_id: Optional[int] = None
    placas: Optional[str] = None
    tipo_mercancia: Optional[str] = None
    tarimas_esperadas: Optional[int] = None
    notas: Optional[str] = None
    oc_id: Optional[int] = None                   # orden de compra que trae el camión (llegadas)
    operador: str = "operador"


class LineaOC(BaseModel):
    sku: str
    piezas_solicitadas: Optional[int] = None
    bultos: int = Field(gt=0)
    piezas_por_bulto: int = Field(gt=0)
    peso_kg: float = Field(gt=0)
    volumen_m3: float = Field(gt=0)


class OrdenIn(BaseModel):
    folio: str = Field(min_length=1)
    folio_factura: str = Field(min_length=1)
    proveedor_id: int
    sucursal_id: int
    lineas: List[LineaOC] = Field(min_length=1)
    operador: str = "operador"


class EscaneoIn(BaseModel):
    codigo: str
    operador: str = "operador"


class AgregarTarimasIn(BaseModel):
    codigos: List[str] = Field(min_length=1)
    operador: str = "operador"


class AbrirSucursalIn(BaseModel):
    codigo: str
    operador: str = "operador"


class CierreSucursalIn(BaseModel):
    observaciones: Optional[str] = None
    operador: str = "operador"


class CierreDescargaIn(BaseModel):
    placas: str
    base_tarima: bool = False
    film_seguridad: bool = False
    altura_maxima: bool = False
    operador: str = "operador"


# ---------------------------------------------------------------- catálogos

@app.get("/api/productos")
def productos():
    return services.listar_catalogo("productos")


@app.get("/api/sucursales")
def sucursales():
    return services.listar_catalogo("sucursales")


@app.get("/api/proveedores")
def proveedores():
    return services.listar_catalogo("proveedores")


@app.get("/api/camiones")
def camiones():
    return services.listar_catalogo("camiones")


# ---------------------------------------------------------------- dashboard

@app.get("/api/dashboard")
def dashboard():
    return services.dashboard()


@app.get("/api/mapa")
def mapa():
    return services.mapa()


@app.get("/api/movimientos")
def movimientos(limite: int = Query(50, ge=1, le=500)):
    return services.listar_movimientos(limite)


# ---------------------------------------------------------------- recepción

@app.post("/api/recepciones", status_code=201)
def crear_recepcion(datos: RecepcionIn):
    resultado = services.registrar_recepcion(
        placas=datos.placas,
        proveedor_id=datos.proveedor_id,
        tipo_mercancia=datos.tipo_mercancia,
        tarimas=[t.model_dump() for t in datos.tarimas],
        tipo_camion=datos.tipo_camion,
        capacidad_camion=datos.capacidad_camion,
        ubicar_automaticamente=datos.ubicar_automaticamente,
        operador=datos.operador,
        cita_id=datos.cita_id,
    )
    agenda.sincronizar_pendientes()  # la cita cumplida se marca como completada en Google
    return resultado


@app.get("/api/recepciones")
def recepciones():
    return services.listar_recepciones()


@app.post("/api/recepciones/{recepcion_id}/ubicar")
def ubicar_recepcion(recepcion_id: int, datos: OperadorIn = OperadorIn()):
    return services.ubicar_recepcion(recepcion_id, datos.operador)


@app.post("/api/tarimas/{codigo}/ubicar")
def ubicar_tarima(codigo: str, datos: OperadorIn = OperadorIn()):
    return services.asignar_ubicacion(codigo, datos.operador)


# --------------------------------------------------------------- inventario

@app.get("/api/inventario")
def inventario(sku: Optional[str] = None, estado: Optional[str] = None):
    return services.inventario(sku, estado)


# ---------------------------------------------------------------- embarques

@app.post("/api/embarques", status_code=201)
def crear_embarque(datos: EmbarqueIn):
    return services.crear_embarque(
        datos.sucursal_id, [i.model_dump() for i in datos.items], datos.operador)


@app.get("/api/embarques")
def embarques(estado: Optional[str] = None):
    return services.listar_embarques(estado)


@app.get("/api/embarques/{embarque_id}")
def embarque(embarque_id: int):
    return services.obtener_embarque(embarque_id)


@app.post("/api/embarques/{embarque_id}/validar")
def validar_embarque(embarque_id: int, datos: ValidacionIn):
    return services.validar_embarque(embarque_id, datos.placas_camion, datos.codigos_escaneados)


@app.post("/api/embarques/{embarque_id}/despachar")
def despachar_embarque(embarque_id: int, datos: OperadorIn = OperadorIn()):
    resultado = services.despachar_embarque(embarque_id, datos.operador)
    agenda.sincronizar_pendientes()
    return resultado


@app.get("/api/embarques/{embarque_id}/sugerencias")
def sugerencias_embarque(embarque_id: int):
    """Qué camión conviene y qué tarimas faltan para cubrir el mínimo de ocupación."""
    return services.sugerir_embarque(embarque_id)


@app.post("/api/embarques/{embarque_id}/agregar")
def agregar_tarimas(embarque_id: int, datos: AgregarTarimasIn):
    return services.agregar_tarimas(embarque_id, datos.codigos, datos.operador)


# ------------------------------------------------- recepción en la sucursal

@app.get("/api/sucursal/despachos")
def despachos_sucursal():
    return sucursal.listar()


@app.post("/api/sucursal/abrir")
def abrir_sucursal(datos: AbrirSucursalIn):
    return sucursal.abrir(datos.codigo, datos.operador)


@app.get("/api/sucursal/{entrega_id}")
def estado_sucursal(entrega_id: int):
    return sucursal.estado(entrega_id)


@app.post("/api/sucursal/{entrega_id}/escanear")
def escanear_sucursal(entrega_id: int, datos: EscaneoIn):
    return sucursal.escanear(entrega_id, datos.codigo, datos.operador)


@app.post("/api/sucursal/{entrega_id}/cerrar")
def cerrar_sucursal(entrega_id: int, datos: CierreSucursalIn):
    return sucursal.cerrar(entrega_id, datos.observaciones, datos.operador)


# ------------------------------------------------- incidencias y reportes

@app.get("/api/incidencias")
def incidencias():
    return control.resumen()


@app.get("/api/reportes/{nombre}.xlsx")
def reporte_excel(nombre: str):
    """Excel con el inventario, movimientos, órdenes, embarques, citas, incidencias o todo junto (`completo`)."""
    return Response(content=reportes.construir(nombre),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="smart-cedis-{nombre}.xlsx"'})


# ------------------------------------------------------------ QR y documentos

@app.get("/api/qr/{codigo}.svg")
def qr(codigo: str):
    """Imagen del código QR de una tarima (T-000012) o de un embarque (E-000001)."""
    svg = documentos.qr_svg(documentos.validar_codigo(codigo))
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/embarques/{embarque_id}/relacion.pdf")
def relacion_embarque(embarque_id: int):
    e = services.obtener_embarque(embarque_id)
    return _pdf(documentos.pdf_relacion_embarque(e), f"relacion-{e['codigo']}.pdf")


@app.get("/api/recepciones/{recepcion_id}/etiquetas.pdf")
def etiquetas_recepcion(recepcion_id: int):
    tarimas = services.datos_etiquetas(recepcion_id=recepcion_id)
    return _pdf(documentos.pdf_etiquetas(tarimas), f"etiquetas-recepcion-{recepcion_id}.pdf")


@app.get("/api/tarimas/{codigo}/etiqueta.pdf")
def etiqueta_tarima(codigo: str):
    tarimas = services.datos_etiquetas(codigo=documentos.validar_codigo(codigo))
    return _pdf(documentos.pdf_etiquetas(tarimas), f"etiqueta-{codigo}.pdf")


# ------------------------------------------------- órdenes de compra y descarga

@app.get("/api/ordenes")
def listar_ordenes(estado: Optional[str] = None):
    return ordenes.listar_ordenes(estado)


@app.post("/api/ordenes", status_code=201)
def crear_orden(datos: OrdenIn):
    d = datos.model_dump()
    return ordenes.crear_orden(d, operador=d.pop("operador"))


@app.get("/api/ordenes/{oc_id}")
def orden(oc_id: int):
    return ordenes.obtener_orden(oc_id)


@app.get("/api/ordenes/{oc_id}/etiquetas.pdf")
def etiquetas_orden(oc_id: int):
    """Etiquetas QR de todos los bultos de la OC: el proveedor las descarga y las pega en cada caja."""
    folio = ordenes.obtener_orden(oc_id)["folio"]
    return _pdf(documentos.pdf_etiquetas_bultos(ordenes.datos_etiquetas_bultos(oc_id=oc_id)), f"etiquetas-{folio}.pdf")


@app.get("/api/bultos/{codigo}/etiqueta.pdf")
def etiqueta_bulto(codigo: str):
    return _pdf(documentos.pdf_etiquetas_bultos(
        ordenes.datos_etiquetas_bultos(codigo=documentos.validar_codigo(codigo))), f"etiqueta-{codigo}.pdf")


@app.get("/api/bultos/{codigo}/qr.svg")
def qr_bulto(codigo: str):
    b = ordenes.datos_etiquetas_bultos(codigo=documentos.validar_codigo(codigo))[0]
    return Response(content=documentos.qr_svg(b["qr"]), media_type="image/svg+xml")


@app.get("/api/descargas/{cita_id}")
def estado_descarga(cita_id: int):
    return ordenes.estado_descarga(cita_id)


@app.post("/api/descargas/{cita_id}/escanear")
def escanear(cita_id: int, datos: EscaneoIn):
    return ordenes.escanear_bulto(cita_id, datos.codigo, datos.operador)


@app.post("/api/descargas/{cita_id}/cerrar")
def cerrar_descarga(cita_id: int, datos: CierreDescargaIn):
    resultado = ordenes.cerrar_descarga(cita_id, datos.placas, datos.base_tarima, datos.film_seguridad,
                                        datos.altura_maxima, datos.operador)
    agenda.sincronizar_pendientes()
    return resultado


# ------------------------------------------------------------------- agenda

@app.get("/api/agenda/config")
def agenda_config():
    return agenda.config()


@app.get("/api/agenda/resumen")
def agenda_resumen():
    return agenda.resumen()


@app.get("/api/citas")
def citas(desde: Optional[str] = None, hasta: Optional[str] = None,
          tipo: Optional[str] = None, estado: Optional[str] = None):
    return agenda.listar_citas(desde, hasta, tipo, estado)


@app.post("/api/citas", status_code=201)
def crear_cita(datos: CitaIn):
    d = datos.model_dump()
    return agenda.crear_cita(d, operador=d.pop("operador"))


@app.get("/api/citas/{cita_id}")
def cita(cita_id: int):
    return agenda.obtener_cita(cita_id)


@app.put("/api/citas/{cita_id}")
def actualizar_cita(cita_id: int, datos: CitaIn):
    return agenda.actualizar_cita(cita_id, datos.model_dump())


@app.post("/api/citas/{cita_id}/cancelar")
def cancelar_cita(cita_id: int):
    return agenda.cancelar_cita(cita_id)


@app.post("/api/citas/{cita_id}/completar")
def completar_cita(cita_id: int):
    return agenda.completar_cita(cita_id)


@app.get("/api/google/estado")
def google_estado(probar: bool = False):
    return agenda.estado_google(probar)


@app.post("/api/google/sincronizar")
def google_sincronizar():
    return agenda.sincronizar_todo()


# --------------------------------------------------------------------- demo

@app.post("/api/demo/reiniciar")
def reiniciar_demo(con_inventario: bool = True, clave: str = ""):
    """Borra todo y deja la base lista para una demostración."""
    services.verificar_clave_reinicio(clave)
    return services.reiniciar(con_inventario)


@app.get("/api/config")
def config_publica():
    """Datos que el frontend necesita saber del servidor (por ahora, si reiniciar pide clave)."""
    return {"reinicio_con_clave": services.reinicio_con_clave()}


# ----------------------------------------------------------------- frontend
# El frontend ya compilado vive en backend/static (se regenera con `npm run build` en /frontend).
STATIC = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def inicio():
    return FileResponse(STATIC / "index.html")
