"""Reportes en Excel (.xlsx): un libro por tema o uno completo con todas las hojas. Requiere openpyxl."""
import io

import agenda
import control
import ordenes
import services
from comun import ErrorNegocio
from database import conexion

NOMBRES = ("inventario", "movimientos", "ordenes", "embarques", "citas", "incidencias", "recepciones", "completo")


def _hojas(nombre):
    """Devuelve [(título de la hoja, encabezados, filas)] del reporte pedido."""
    todas = {}

    inv = services.inventario()["tarimas"]
    todas["inventario"] = ("Inventario", ["Tarima", "SKU", "Producto", "Unidades", "Peso (kg)", "Estado", "Ubicación", "Recepción"],
                           [[t["codigo"], t["sku"], t["producto"], t["cantidad"], t["peso_kg"], t["estado"], t["ubicacion"], t["recepcion_id"]] for t in inv])
    mov = services.listar_movimientos(100000)
    todas["movimientos"] = ("Movimientos", ["Fecha", "Tarima", "Tipo", "Origen", "Destino", "Operador"],
                            [[m["fecha"], m["tarima"], m["tipo"], m["origen"], m["destino"], m["operador"]] for m in mov])
    ocs = ordenes.listar_ordenes()
    with conexion() as conn:
        bultos = conn.execute(
            "SELECT b.codigo, o.folio, o.folio_factura, p.sku, b.piezas, b.peso_kg, b.volumen_m3, b.estado, t.codigo AS tarima "
            "FROM bultos b JOIN ordenes_compra o ON o.id = b.oc_id JOIN productos p ON p.id = b.producto_id "
            "LEFT JOIN tarimas t ON t.id = b.tarima_id ORDER BY b.id").fetchall()
        inc = control.lista_incidencias(conn)
    todas["ordenes"] = ("Órdenes de compra", ["OC", "Factura", "Proveedor", "Sucursal destino", "Estado", "Bultos", "Recibidos"],
                        [[o["folio"], o["folio_factura"], o["proveedor"], o["sucursal"], o["estado"], o["bultos"], o["recibidos"]] for o in ocs])
    todas["bultos"] = ("Bultos", ["Bulto", "OC", "Factura", "SKU", "Piezas", "Peso (kg)", "Volumen (m³)", "Estado", "Tarima"],
                       [list(b) for b in bultos])
    emb = services.listar_embarques()
    todas["embarques"] = ("Embarques", ["Embarque", "Sucursal", "Estado", "Camión", "Tarimas", "Creado", "Salida"],
                          [[e["codigo"], e["sucursal"], e["estado"], e["placas"], e["tarimas"], e["fecha_creacion"], e["fecha_salida"]] for e in emb])
    citas = agenda.listar_citas()
    todas["citas"] = ("Agenda", ["Cita", "Tipo", "Inicio", "Fin", "Andén", "Estado", "Título", "OC", "Placas"],
                      [[c["id"], c["tipo"], c["inicio"], c["fin"], c["anden"], c["estado"], c["titulo"], c["oc_folio"], c["placas"]] for c in citas])
    todas["incidencias"] = ("Incidencias", ["Fecha", "Origen", "Tipo", "Código", "Detalle", "OC", "Embarque", "Operador"],
                            [[i["fecha"], i["origen"], i["tipo_nombre"], i["codigo"], i["motivo"], i["oc"], i["embarque"], i["operador"]] for i in inc])
    rec = services.listar_recepciones()
    todas["recepciones"] = ("Recepciones", ["#", "Llegada", "Camión", "Proveedor", "Mercancía", "Tarimas", "Por ubicar"],
                            [[r["id"], r["fecha_llegada"], r["placas"], r["proveedor"], r["tipo_mercancia"], r["tarimas"], r["por_ubicar"]] for r in rec])
    if nombre == "completo":
        orden = ["inventario", "movimientos", "ordenes", "bultos", "embarques", "citas", "incidencias", "recepciones"]
        return [todas[k] for k in orden]
    if nombre == "ordenes":
        return [todas["ordenes"], todas["bultos"]]
    return [todas[nombre]]


def construir(nombre):
    """Genera el archivo .xlsx (bytes) del reporte `nombre`."""
    if nombre not in NOMBRES:
        raise ErrorNegocio(f"No existe el reporte '{nombre}'. Opciones: {', '.join(NOMBRES)}.")
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise ErrorNegocio("Para exportar a Excel instala openpyxl:  pip3 install openpyxl")
    libro = Workbook()
    libro.remove(libro.active)
    relleno = PatternFill("solid", fgColor="1B2330")
    for titulo, encabezados, filas in _hojas(nombre):
        hoja = libro.create_sheet(titulo[:31])
        hoja.append(encabezados)
        for fila in filas:
            hoja.append(fila)
        for celda in hoja[1]:
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = relleno
            celda.alignment = Alignment(vertical="center")
        hoja.freeze_panes = "A2"
        if filas:
            hoja.auto_filter.ref = hoja.dimensions
        for i, encabezado in enumerate(encabezados, 1):
            ancho = max([len(str(encabezado))] + [len(str(f[i - 1])) for f in filas[:300] if f[i - 1] is not None])
            hoja.column_dimensions[get_column_letter(i)].width = min(max(ancho + 3, 10), 60)
    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()
