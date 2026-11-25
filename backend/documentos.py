"""Códigos QR y documentos PDF de Smart CEDIS (relación de embarque y etiquetas de tarima).

El QR de una tarima contiene su código ("T-000012") y el de un embarque su folio ("E-000001").
Es texto plano a propósito: un lector de QR "teclea" el código, así que sirve igual en el
cuadro de escaneo de la validación de carga.
"""
import io
import re
from datetime import datetime

from reportlab.graphics.barcode import qrencoder
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, inch
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas
from reportlab.platypus import (Flowable, KeepTogether, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

_CODIGO = re.compile(r"^[A-Z]-\d{1,9}$")

OSCURO = colors.HexColor("#1b2330")
ACENTO = colors.HexColor("#f5b301")
GRIS = colors.HexColor("#5b6675")
ZEBRA = colors.HexColor("#f3f5f8")
LINEA = colors.HexColor("#c9d0da")

ESTADOS_EMBARQUE = {
    "pendiente": "Pendiente de validar",
    "validado": "Validado, listo para salir",
    "despachado": "Despachado",
}


class CodigoInvalido(ValueError):
    pass


def validar_codigo(codigo):
    if not _CODIGO.match(codigo or ""):
        raise CodigoInvalido(f"'{codigo}' no es un código válido (ej. T-000012 o E-000001).")
    return codigo


# ------------------------------------------------------------------------ QR

def matriz_qr(valor):
    """Matriz de módulos del QR (True = oscuro), con corrección de errores nivel M."""
    qr = qrencoder.QRCode(None, qrencoder.QRErrorCorrectLevel.M)
    qr.addData(valor)
    qr.make()
    n = qr.getModuleCount()
    return [[bool(qr.isDark(r, c)) for c in range(n)] for r in range(n)]


def qr_svg(valor, borde=2):
    """SVG compacto (un solo trazo) con fondo blanco y margen de silencio."""
    matriz = matriz_qr(valor)
    n = len(matriz)
    trazo = []
    for r, fila in enumerate(matriz):
        c = 0
        while c < n:
            if fila[c]:
                inicio = c
                while c < n and fila[c]:
                    c += 1
                trazo.append(f"M{inicio + borde} {r + borde}h{c - inicio}v1h-{c - inicio}z")
            else:
                c += 1
    lado = n + 2 * borde
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lado} {lado}" '
            f'shape-rendering="crispEdges"><rect width="{lado}" height="{lado}" fill="#fff"/>'
            f'<path fill="#000" d="{"".join(trazo)}"/></svg>')


def dibujar_qr(c, valor, x, y, tam):
    """Dibuja el QR en el canvas con su esquina inferior izquierda en (x, y)."""
    matriz = matriz_qr(valor)
    n = len(matriz)
    modulo = tam / n
    c.saveState()
    c.setFillColor(colors.black)
    trazo = c.beginPath()
    for r, fila in enumerate(matriz):
        col = 0
        while col < n:
            if fila[col]:
                inicio = col
                while col < n and fila[col]:
                    col += 1
                trazo.rect(x + inicio * modulo, y + tam - (r + 1) * modulo, (col - inicio) * modulo, modulo)
            else:
                col += 1
    c.drawPath(trazo, stroke=0, fill=1)
    c.restoreState()


class QRFlowable(Flowable):
    def __init__(self, valor, tam):
        super().__init__()
        self.valor = valor
        self.tam = tam
        self.width = self.height = tam

    def wrap(self, ancho, alto):
        return self.tam, self.tam

    def draw(self):
        dibujar_qr(self.canv, self.valor, 0, 0, self.tam)


class Casilla(Flowable):
    """Cuadro vacío para palomear la tarima al recibirla."""
    def __init__(self, lado=0.42 * cm):
        super().__init__()
        self.lado = lado
        self.width = self.height = lado

    def wrap(self, ancho, alto):
        return self.lado, self.lado

    def draw(self):
        self.canv.setStrokeColor(GRIS)
        self.canv.setLineWidth(0.8)
        self.canv.rect(0, 0, self.lado, self.lado)


# --------------------------------------------------------------------- utilidades

def _fecha(iso):
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M") if iso else "—"


def _num(n, decimales=0):
    return f"{n:,.{decimales}f}"


def _estilo(nombre, **kw):
    base = dict(fontName="Helvetica", fontSize=9, leading=11.5, textColor=OSCURO)
    base.update(kw)
    return ParagraphStyle(nombre, **base)


class _CanvasNumerado(canvas.Canvas):
    """Canvas que escribe 'Página x de y' y el pie en todas las páginas."""

    def __init__(self, *args, pie="", **kwargs):
        super().__init__(*args, **kwargs)
        self._pie = pie
        self._paginas = []

    def showPage(self):
        self._paginas.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._paginas)
        for estado in self._paginas:
            self.__dict__.update(estado)
            self.setStrokeColor(LINEA)
            self.setLineWidth(0.6)
            self.line(1.6 * cm, 1.5 * cm, letter[0] - 1.6 * cm, 1.5 * cm)
            self.setFont("Helvetica", 7.5)
            self.setFillColor(GRIS)
            self.drawString(1.6 * cm, 1.05 * cm, self._pie)
            self.drawRightString(letter[0] - 1.6 * cm, 1.05 * cm, f"Página {self._pagina_actual()} de {total}")
            super().showPage()
        super().save()

    def _pagina_actual(self):
        return self._pageNumber


# ------------------------------------------------------- relación de embarque (PDF)

def pdf_relacion_embarque(e):
    """Genera el PDF de la relación de embarque a partir de `services.obtener_embarque()`."""
    tarimas = e["tarimas"]
    total_unidades = sum(t["cantidad"] for t in tarimas)
    total_peso = sum(t["peso_kg"] for t in tarimas)

    st_peq = _estilo("peq", fontSize=7.5, leading=9, textColor=GRIS)
    st_tabla = _estilo("tabla", fontSize=8.5, leading=10.5)
    st_cab = _estilo("cab", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white)
    st_cab_der = _estilo("cabder", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white, alignment=2)
    st_der = _estilo("der", fontSize=8.5, leading=10.5, alignment=2)
    st_etq = _estilo("etq", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=GRIS)

    historia = []

    # Encabezado: título y folio a la izquierda, QR del embarque a la derecha
    izquierda = [
        Paragraph("SMART CEDIS · CENTRO DE DISTRIBUCIÓN", _estilo("m", fontName="Helvetica-Bold", fontSize=8, textColor=GRIS)),
        Spacer(1, 3),
        Paragraph("Relación de embarque", _estilo("t", fontName="Helvetica-Bold", fontSize=21, leading=25)),
        Paragraph(e["codigo"], _estilo("f", fontName="Courier-Bold", fontSize=22, leading=27, textColor=colors.HexColor("#b07d00"))),
    ]
    derecha = [QRFlowable(e["codigo"], 3.0 * cm), Spacer(1, 2),
               Paragraph("Escanea para identificar el embarque", _estilo("qc", fontSize=6.5, leading=8, textColor=GRIS, alignment=1))]
    cabecera = Table([[izquierda, derecha]], colWidths=[14.0 * cm, 4.4 * cm])
    cabecera.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                                  ("LINEBELOW", (0, 0), (-1, 0), 2, ACENTO), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    historia += [cabecera, Spacer(1, 10)]

    if e["estado"] != "despachado":
        historia += [Paragraph(
            f"<b>Documento preliminar.</b> El embarque está <b>{ESTADOS_EMBARQUE[e['estado']].lower()}</b> y "
            "todavía no ha salido del CEDIS; la fecha de salida y los datos del camión pueden cambiar.",
            _estilo("aviso", fontSize=8.5, backColor=colors.HexColor("#fff4d6"), borderPadding=(5, 6, 5, 6),
                    borderColor=ACENTO, borderWidth=0.6, leading=11)), Spacer(1, 12)]

    # Datos generales en dos columnas
    datos = [
        ("Sucursal destino", e["sucursal"], "Camión (placas)", e["placas"] or "Por asignar"),
        ("Destino", e["destino"], "Tipo de camión", e["tipo_camion"] or "—"),
        ("Fecha de creación", _fecha(e["fecha_creacion"]), "Fecha de salida", _fecha(e["fecha_salida"])),
        ("Estado", ESTADOS_EMBARQUE[e["estado"]], "Operador", e["operador"]),
        ("Peso total", f"{_num(e['peso_kg'], 1)} kg", "Volumen total", f"{_num(e['volumen_m3'], 2)} m³"),
    ]
    if e.get("ocupacion"):
        o = e["ocupacion"]
        datos.append(("Ocupación del camión", f"{o['peso_pct']}% del peso · {o['volumen_pct']}% del volumen",
                      "Mínimo para salir", f"{o['minimo_pct']}%"))
    filas = [[Paragraph(a, st_etq), Paragraph(b, st_tabla), Paragraph(c, st_etq), Paragraph(d, st_tabla)]
             for a, b, c, d in datos]
    grid = Table(filas, colWidths=[3.1 * cm, 6.1 * cm, 3.1 * cm, 6.1 * cm])
    grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINEA)]))
    historia += [grid, Spacer(1, 10)]

    # Tabla de tarimas (con QR por tarima para escanear al recibir)
    historia.append(Paragraph(f"Tarimas del embarque ({len(tarimas)})",
                              _estilo("h", fontName="Helvetica-Bold", fontSize=11, leading=14)))
    historia.append(Spacer(1, 4))
    filas = [[Paragraph("#", st_cab), Paragraph("TARIMA", st_cab), Paragraph("PRODUCTO", st_cab),
              Paragraph("UNIDADES", st_cab_der), Paragraph("PESO (KG)", st_cab_der),
              Paragraph("UBICACIÓN", st_cab), Paragraph("QR", st_cab), Paragraph("REV.", st_cab)]]
    for i, t in enumerate(tarimas, 1):
        filas.append([
            Paragraph(str(i), st_tabla),
            Paragraph(f"<font name='Courier-Bold'>{t['codigo']}</font>", st_tabla),
            Paragraph(f"<b>{t['sku']}</b><br/>{t['producto']}", st_tabla),
            Paragraph(_num(t["cantidad"]), st_der),
            Paragraph(_num(t["peso_kg"], 1), st_der),
            Paragraph(t["ubicacion"] or t["origen"] or "—", st_tabla),
            QRFlowable(t["codigo"], 1.15 * cm),
            Casilla(),
        ])
    tabla = Table(filas, colWidths=[0.8 * cm, 2.5 * cm, 5.0 * cm, 2.2 * cm, 2.3 * cm, 2.4 * cm, 1.8 * cm, 1.4 * cm],
                  repeatRows=1)
    estilo = [("BACKGROUND", (0, 0), (-1, 0), OSCURO), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
              ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINEA), ("ALIGN", (6, 1), (7, -1), "CENTER")]
    for r in range(2, len(filas), 2):
        estilo.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
    tabla.setStyle(TableStyle(estilo))
    historia += [tabla, Spacer(1, 10)]

    # Bultos (cajas) agrupados por sucursal destino: lo que se revisa al recibir en la sucursal
    bultos = e.get("bultos") or []
    if bultos:
        historia.append(Paragraph(
            f"Bultos para {e['sucursal']} ({len(bultos)})", _estilo("hb", fontName="Helvetica-Bold", fontSize=11, leading=14)))
        historia.append(Spacer(1, 4))
        filas = [[Paragraph("BULTO", st_cab), Paragraph("OC / FACTURA", st_cab), Paragraph("PRODUCTO", st_cab),
                  Paragraph("PIEZAS", st_cab_der), Paragraph("PESO (KG)", st_cab_der), Paragraph("TARIMA", st_cab),
                  Paragraph("REV.", st_cab)]]
        for b in bultos:
            filas.append([
                Paragraph(f"<font name='Courier-Bold'>{b['codigo']}</font>", st_tabla),
                Paragraph(f"{b['oc']}<br/><font color='#5b6675'>{b['factura']}</font>", st_tabla),
                Paragraph(f"<b>{b['sku']}</b> {b['producto']}", st_tabla),
                Paragraph(_num(b["piezas"]), st_der), Paragraph(_num(b["peso_kg"], 1), st_der),
                Paragraph(f"<font name='Courier'>{b['tarima']}</font>", st_tabla), Casilla(0.36 * cm)])
        tb = Table(filas, colWidths=[2.3 * cm, 3.4 * cm, 5.6 * cm, 1.6 * cm, 1.9 * cm, 2.4 * cm, 1.2 * cm], repeatRows=1)
        est = [("BACKGROUND", (0, 0), (-1, 0), OSCURO), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
               ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
               ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINEA), ("ALIGN", (6, 1), (6, -1), "CENTER")]
        for r in range(2, len(filas), 2):
            est.append(("BACKGROUND", (0, r), (-1, r), ZEBRA))
        tb.setStyle(TableStyle(est))
        historia += [tb, Spacer(1, 10)]

    # Resumen por producto con totales
    resumen = {}
    for t in tarimas:
        r = resumen.setdefault(t["sku"], {"producto": t["producto"], "tarimas": 0, "unidades": 0, "peso": 0.0})
        r["tarimas"] += 1
        r["unidades"] += t["cantidad"]
        r["peso"] += t["peso_kg"]
    filas = [[Paragraph("SKU", st_cab), Paragraph("PRODUCTO", st_cab), Paragraph("TARIMAS", st_cab_der),
              Paragraph("UNIDADES", st_cab_der), Paragraph("PESO (KG)", st_cab_der)]]
    for sku, r in sorted(resumen.items()):
        filas.append([Paragraph(sku, st_tabla), Paragraph(r["producto"], st_tabla), Paragraph(str(r["tarimas"]), st_der),
                      Paragraph(_num(r["unidades"]), st_der), Paragraph(_num(r["peso"], 1), st_der)])
    negrita = _estilo("neg", fontName="Helvetica-Bold", fontSize=9, leading=11)
    negrita_der = _estilo("negder", parent=negrita, alignment=2)
    filas.append([Paragraph("TOTAL", negrita), "", Paragraph(str(len(tarimas)), negrita_der),
                  Paragraph(_num(total_unidades), negrita_der), Paragraph(_num(total_peso, 1), negrita_der)])
    resumen_t = Table(filas, colWidths=[2.6 * cm, 8.2 * cm, 2.2 * cm, 2.6 * cm, 2.8 * cm])
    resumen_t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), OSCURO), ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5), ("LINEBELOW", (0, 1), (-1, -2), 0.4, LINEA),
                                   ("LINEABOVE", (0, -1), (-1, -1), 1, OSCURO),
                                   ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fff4d6"))]))
    historia.append(KeepTogether([
        Paragraph("Resumen por producto", _estilo("h2", fontName="Helvetica-Bold", fontSize=11, leading=14)),
        Spacer(1, 4), resumen_t]))
    historia.append(Spacer(1, 10))

    # Observaciones y firmas
    caja = Table([[Paragraph("OBSERVACIONES / INCIDENCIAS EN LA ENTREGA", st_etq)], [""]],
                 colWidths=[18.4 * cm], rowHeights=[0.55 * cm, 1.3 * cm])
    caja.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINEA), ("LINEBELOW", (0, 0), (-1, 0), 0.4, LINEA),
                              ("LEFTPADDING", (0, 0), (-1, -1), 6), ("VALIGN", (0, 0), (-1, 0), "MIDDLE")]))
    firmas = Table(
        [["", "", "", "", ""],
         [Paragraph("<b>Entregó (CEDIS)</b><br/>Nombre, firma y fecha", st_peq), "",
          Paragraph("<b>Transportista</b><br/>Nombre, firma y fecha", st_peq), "",
          Paragraph("<b>Recibió (sucursal)</b><br/>Nombre, firma y fecha", st_peq)]],
        colWidths=[5.6 * cm, 0.8 * cm, 5.6 * cm, 0.8 * cm, 5.6 * cm], rowHeights=[1.3 * cm, None])
    firmas.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.8, OSCURO), ("LINEABOVE", (2, 1), (2, 1), 0.8, OSCURO),
                                ("LINEABOVE", (4, 1), (4, 1), 0.8, OSCURO), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 1), (-1, 1), 3)]))
    historia.append(KeepTogether([caja, Spacer(1, 6), firmas]))

    buffer = io.BytesIO()
    pie = f"Smart CEDIS · Relación de embarque {e['codigo']} · Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=1.6 * cm, rightMargin=1.6 * cm,
                            topMargin=1.5 * cm, bottomMargin=2.0 * cm,
                            title=f"Relación de embarque {e['codigo']}", author="Smart CEDIS")
    doc.build(historia, canvasmaker=lambda *a, **k: _CanvasNumerado(*a, pie=pie, **k))
    return buffer.getvalue()


# ------------------------------------------------------------ etiquetas de tarima (PDF)

ETIQUETA = (4 * inch, 6 * inch)


def _etiqueta(c, t):
    ancho, alto = ETIQUETA
    m = 14
    arriba = lambda y: alto - y  # noqa: E731  (medimos desde arriba para razonar el diseño)

    c.setStrokeColor(OSCURO)
    c.setLineWidth(1.2)
    c.roundRect(m / 2, m / 2, ancho - m, alto - m, 8)

    # Banda superior
    c.setFillColor(OSCURO)
    c.roundRect(m / 2, arriba(46), ancho - m, 38, 8, stroke=0, fill=1)
    c.rect(m / 2, arriba(46), ancho - m, 20, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(m + 6, arriba(34), "SMART CEDIS")
    c.setFillColor(ACENTO)
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(ancho - m - 6, arriba(34), "TARIMA")

    # QR centrado
    lado = 160
    dibujar_qr(c, t["codigo"], (ancho - lado) / 2, arriba(60 + lado), lado)

    # Código
    c.setFillColor(OSCURO)
    c.setFont("Courier-Bold", 30)
    c.drawCentredString(ancho / 2, arriba(60 + lado + 34), t["codigo"])

    # Producto
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(ancho / 2, arriba(60 + lado + 58), t["sku"])
    c.setFont("Helvetica", 10.5)
    y = 60 + lado + 74
    for linea in simpleSplit(t["producto"], "Helvetica", 10.5, ancho - 3 * m)[:2]:
        c.drawCentredString(ancho / 2, arriba(y), linea)
        y += 13

    # Unidades y peso
    y_caja = 60 + lado + 94
    mitad = (ancho - 2 * m - 8) / 2
    for i, (etq, valor) in enumerate((("UNIDADES", _num(t["cantidad"])), ("PESO", f"{_num(t['peso_kg'], 1)} kg"))):
        x = m + i * (mitad + 8)
        c.setStrokeColor(LINEA)
        c.setLineWidth(0.8)
        c.roundRect(x, arriba(y_caja + 36), mitad, 36, 5)
        c.setFillColor(GRIS)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x + 7, arriba(y_caja + 11), etq)
        c.setFillColor(OSCURO)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(x + 7, arriba(y_caja + 29), valor)

    # Ubicación
    y_ub = y_caja + 44
    c.setFillColor(GRIS)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(m + 7, arriba(y_ub + 8), "UBICACIÓN")
    c.setFillColor(OSCURO)
    c.setFont("Helvetica-Bold", 20 if t["ubicacion"] else 15)
    c.drawString(m + 7, arriba(y_ub + 30), t["ubicacion"] or "POR UBICAR")

    # Pie
    c.setFillColor(GRIS)
    c.setFont("Helvetica", 7)
    c.drawCentredString(ancho / 2, arriba(alto - 20),
                        f"Recepción #{t['recepcion_id']} · {t['placas']} · {_fecha(t['fecha_llegada'])}")


def pdf_etiquetas(tarimas):
    """Una etiqueta de 4x6 pulgadas por tarima (`services.datos_etiquetas()`)."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=ETIQUETA, pageCompression=1)
    c.setTitle("Etiquetas de tarima" if len(tarimas) > 1 else f"Etiqueta {tarimas[0]['codigo']}")
    c.setAuthor("Smart CEDIS")
    for t in tarimas:
        _etiqueta(c, t)
        c.showPage()
    c.save()
    return buffer.getvalue()


# ------------------------------------------------------------ etiquetas de bulto (PDF)

ETIQUETA_BULTO = (4 * inch, 3 * inch)


def _etiqueta_bulto(c, b):
    """Etiqueta de caja: QR con bulto, OC, proveedor, sucursal destino, SKU y piezas (también impresos en texto)."""
    ancho, alto = ETIQUETA_BULTO
    m = 10
    c.setStrokeColor(OSCURO)
    c.setLineWidth(1.2)
    c.roundRect(m / 2, m / 2, ancho - m, alto - m, 6)
    c.setFillColor(OSCURO)
    c.roundRect(m / 2, alto - 30, ancho - m, 25, 6, stroke=0, fill=1)
    c.rect(m / 2, alto - 30, ancho - m, 12, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(m + 4, alto - 22, "SMART CEDIS")
    c.setFillColor(ACENTO)
    c.drawRightString(ancho - m - 4, alto - 22, "BULTO")

    lado = 112
    dibujar_qr(c, b["qr"], m + 2, alto - 38 - lado, lado)
    c.setFillColor(OSCURO)
    c.setFont("Courier-Bold", 14)
    c.drawString(m + 2, alto - 38 - lado - 14, b["codigo"])

    x = m + lado + 10
    y = alto - 48
    campos = [("OC", b["oc_folio"]), ("FACTURA", b["folio_factura"]), ("PROVEEDOR", b["proveedor"]),
              ("DESTINO", b["sucursal"]), ("SKU", f"{b['sku']} · {b['producto']}")]
    for etq, valor in campos:
        c.setFillColor(GRIS)
        c.setFont("Helvetica-Bold", 6)
        c.drawString(x, y, etq)
        c.setFillColor(OSCURO)
        c.setFont("Helvetica-Bold", 8.5)
        lineas = simpleSplit(valor, "Helvetica-Bold", 8.5, ancho - x - m - 4)[:2]
        for i, linea in enumerate(lineas):
            c.drawString(x, y - 9 - 9 * i, linea)
        y -= 9 + 9 * len(lineas) + 5
    c.setFillColor(OSCURO)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(x, m + 6, f"{b['piezas']} pzas")
    c.setFillColor(GRIS)
    c.setFont("Helvetica", 7)
    c.drawRightString(ancho - m - 4, m + 8, f"{_num(b['peso_kg'], 1)} kg")


def pdf_etiquetas_bultos(bultos):
    """Una etiqueta de 4x3 pulgadas por bulto (`ordenes.datos_etiquetas_bultos()`)."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=ETIQUETA_BULTO, pageCompression=1)
    c.setTitle(f"Etiquetas de bultos {bultos[0]['oc_folio']}")
    c.setAuthor("Smart CEDIS")
    for b in bultos:
        _etiqueta_bulto(c, b)
        c.showPage()
    c.save()
    return buffer.getvalue()
