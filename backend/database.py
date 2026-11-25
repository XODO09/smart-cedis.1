"""Base de datos SQLite de Smart CEDIS: esquema, conexión y catálogos de ejemplo."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("CEDIS_DB") or Path(__file__).with_name("cedis.db"))

# Geometría del almacén: 32 racks x 4 niveles x 6 posiciones = 768 ubicaciones
NUM_RACKS = 32
NIVELES = 4
POSICIONES = 6

# Andenes (muelles) del CEDIS para recibir y despachar camiones; la agenda evita dobles citas en uno
NUM_ANDENES = 4

# Reglas de la agenda: citas por andén en horario corrido; descargar toma mínimo 1 hora
HORA_INICIO_CITAS = 8
HORA_FIN_CITAS = 18
DURACION_MIN_CITA = 60

# Un camión no sale hasta cubrir al menos este porcentaje de su capacidad.
# "cualquiera": basta con llegar al 90 % en peso o en volumen (lo normal: un camión se llena por el límite que toque primero).
# "ambos": exige el 90 % en peso y en volumen a la vez.
OCUPACION_MINIMA = 0.90
CRITERIO_OCUPACION = "cualquiera"

# Tablas en orden de borrado (primero las que dependen de otras)
TABLAS = [
    "incidencias", "entrega_items", "entregas", "citas", "bultos", "oc_lineas", "movimientos", "embarque_tarimas", "embarques", "tarimas", "ordenes_compra", "recepciones",
    "ubicaciones", "racks", "camiones", "proveedores", "sucursales", "productos",
]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS productos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sku         TEXT NOT NULL UNIQUE,
    nombre      TEXT NOT NULL,
    descripcion TEXT
);

CREATE TABLE IF NOT EXISTS sucursales (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL,
    destino TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proveedores (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS camiones (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    placas            TEXT NOT NULL UNIQUE,
    tipo              TEXT NOT NULL,
    capacidad_tarimas INTEGER NOT NULL CHECK (capacidad_tarimas > 0),
    capacidad_kg      REAL NOT NULL DEFAULT 10000,
    capacidad_m3      REAL NOT NULL DEFAULT 25
);

-- Un rack es un lugar físico del CEDIS; no pertenece a ninguna sucursal.
CREATE TABLE IF NOT EXISTS racks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo     TEXT NOT NULL UNIQUE,
    niveles    INTEGER NOT NULL,
    posiciones INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS ubicaciones (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    rack_id  INTEGER NOT NULL REFERENCES racks(id),
    nivel    INTEGER NOT NULL,
    posicion INTEGER NOT NULL,
    codigo   TEXT NOT NULL UNIQUE,
    UNIQUE (rack_id, nivel, posicion)
);

CREATE TABLE IF NOT EXISTS recepciones (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    camion_id      INTEGER NOT NULL REFERENCES camiones(id),
    proveedor_id   INTEGER NOT NULL REFERENCES proveedores(id),
    tipo_mercancia TEXT NOT NULL,
    fecha_llegada  TEXT NOT NULL,
    operador       TEXT NOT NULL
);

-- estado: recibida -> almacenada -> asignada (a un embarque) -> despachada
CREATE TABLE IF NOT EXISTS tarimas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo       TEXT UNIQUE,
    producto_id  INTEGER NOT NULL REFERENCES productos(id),
    cantidad     INTEGER NOT NULL CHECK (cantidad > 0),
    peso_kg      REAL NOT NULL CHECK (peso_kg > 0),
    recepcion_id INTEGER NOT NULL REFERENCES recepciones(id),
    ubicacion_id INTEGER REFERENCES ubicaciones(id),
    estado       TEXT NOT NULL DEFAULT 'recibida'
                 CHECK (estado IN ('recibida', 'almacenada', 'asignada', 'despachada')),
    volumen_m3   REAL NOT NULL DEFAULT 1.2,
    sucursal_id  INTEGER REFERENCES sucursales(id),   -- destino, cuando viene de una OC
    oc_id        INTEGER REFERENCES ordenes_compra(id)
);

-- Una ubicación solo puede tener una tarima a la vez
CREATE UNIQUE INDEX IF NOT EXISTS idx_tarima_ubicacion
    ON tarimas(ubicacion_id) WHERE ubicacion_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tarimas_estado ON tarimas(estado, producto_id);

CREATE TABLE IF NOT EXISTS embarques (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    sucursal_id    INTEGER NOT NULL REFERENCES sucursales(id),
    camion_id      INTEGER REFERENCES camiones(id),
    estado         TEXT NOT NULL DEFAULT 'pendiente'
                   CHECK (estado IN ('pendiente', 'validado', 'despachado')),
    fecha_creacion TEXT NOT NULL,
    fecha_salida   TEXT,
    operador       TEXT NOT NULL
);

-- Una tarima solo puede pertenecer a un embarque
CREATE TABLE IF NOT EXISTS embarque_tarimas (
    embarque_id INTEGER NOT NULL REFERENCES embarques(id),
    tarima_id   INTEGER NOT NULL UNIQUE REFERENCES tarimas(id),
    PRIMARY KEY (embarque_id, tarima_id)
);

-- Orden de compra: cada OC lleva un folio de factura propio (no se puede repetir)
CREATE TABLE IF NOT EXISTS ordenes_compra (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    folio         TEXT NOT NULL UNIQUE,
    folio_factura TEXT NOT NULL UNIQUE,
    proveedor_id  INTEGER NOT NULL REFERENCES proveedores(id),
    sucursal_id   INTEGER NOT NULL REFERENCES sucursales(id),
    estado        TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'parcial', 'recibida')),
    creada        TEXT NOT NULL,
    operador      TEXT NOT NULL
);

-- Lo que se solicitó en la OC, por producto
CREATE TABLE IF NOT EXISTS oc_lineas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    oc_id       INTEGER NOT NULL REFERENCES ordenes_compra(id),
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    piezas      INTEGER NOT NULL CHECK (piezas > 0),
    UNIQUE (oc_id, producto_id)
);

-- Desglose de la factura: un bulto (caja) lleva un solo producto
CREATE TABLE IF NOT EXISTS bultos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo      TEXT UNIQUE,
    oc_id       INTEGER NOT NULL REFERENCES ordenes_compra(id),
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    piezas      INTEGER NOT NULL CHECK (piezas > 0),
    peso_kg     REAL NOT NULL CHECK (peso_kg > 0),
    volumen_m3  REAL NOT NULL CHECK (volumen_m3 > 0),
    estado      TEXT NOT NULL DEFAULT 'esperado' CHECK (estado IN ('esperado', 'escaneado', 'recibido')),
    tarima_id   INTEGER REFERENCES tarimas(id),
    escaneado   TEXT
);
CREATE INDEX IF NOT EXISTS idx_bultos_oc ON bultos(oc_id, estado);

-- Bultos rechazados al descargar (no solicitados, repetidos, de otra OC)
CREATE TABLE IF NOT EXISTS incidencias (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    cita_id  INTEGER REFERENCES citas(id),
    oc_id    INTEGER REFERENCES ordenes_compra(id),
    codigo   TEXT NOT NULL,
    motivo   TEXT NOT NULL,
    fecha    TEXT NOT NULL,
    operador TEXT NOT NULL,
    tipo       TEXT,       -- no_existe, otra_oc, etiqueta, repetido, ajeno_destino, repetido_destino, faltante_destino
    entrega_id INTEGER REFERENCES entregas(id)
);

-- Recepción en la sucursal: se escanea el QR del embarque y luego cada bulto (o tarima) que llega
CREATE TABLE IF NOT EXISTS entregas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    embarque_id   INTEGER NOT NULL UNIQUE REFERENCES embarques(id),
    estado        TEXT NOT NULL DEFAULT 'abierta' CHECK (estado IN ('abierta', 'cerrada')),
    inicio        TEXT NOT NULL,
    cierre        TEXT,
    operador      TEXT NOT NULL,
    observaciones TEXT,
    esperados     INTEGER,
    recibidos     INTEGER
);
CREATE TABLE IF NOT EXISTS entrega_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entrega_id INTEGER NOT NULL REFERENCES entregas(id),
    codigo     TEXT NOT NULL,
    fecha      TEXT NOT NULL,
    UNIQUE (entrega_id, codigo)
);

-- Agenda: citas de llegada (proveedores) y de entrega (sucursales). Las fechas son hora local ISO.
CREATE TABLE IF NOT EXISTS citas (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo              TEXT NOT NULL CHECK (tipo IN ('llegada', 'entrega')),
    inicio            TEXT NOT NULL,
    fin               TEXT NOT NULL,
    anden             INTEGER NOT NULL,
    estado            TEXT NOT NULL DEFAULT 'programada'
                      CHECK (estado IN ('programada', 'completada', 'cancelada')),
    proveedor_id      INTEGER REFERENCES proveedores(id),
    sucursal_id       INTEGER REFERENCES sucursales(id),
    embarque_id       INTEGER REFERENCES embarques(id),
    recepcion_id      INTEGER REFERENCES recepciones(id),
    oc_id             INTEGER REFERENCES ordenes_compra(id),
    placas            TEXT,
    tipo_mercancia    TEXT,
    tarimas_esperadas INTEGER,
    notas             TEXT,
    operador          TEXT NOT NULL,
    creada            TEXT NOT NULL,
    -- Sincronización con Google Calendar (todo NULL si no hay conexión)
    google_event_id   TEXT,
    google_link       TEXT,
    google_estado     TEXT CHECK (google_estado IN ('pendiente', 'sincronizado', 'error')),
    google_error      TEXT,
    google_sync       TEXT
);
CREATE INDEX IF NOT EXISTS idx_citas_inicio ON citas(inicio);

CREATE TABLE IF NOT EXISTS movimientos (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tarima_id INTEGER NOT NULL REFERENCES tarimas(id),
    tipo      TEXT NOT NULL,
    origen    TEXT NOT NULL,
    destino   TEXT NOT NULL,
    fecha     TEXT NOT NULL,
    operador  TEXT NOT NULL
);
"""

PRODUCTOS = [
    ("SKU-1001", "Cuaderno profesional 100 hojas", "Caja con 12 piezas"),
    ("SKU-1002", "Pegamento blanco 1 L", "Caja con 20 piezas"),
    ("SKU-1003", "Lápiz del No. 2, caja de 12", "Caja con 20 piezas"),
    ("SKU-1004", "Papel bond carta 500 hojas", "Caja con 10 piezas"),
    ("SKU-2001", "Folder manila carta, paquete de 100", "Caja con 24 piezas"),
    ("SKU-2002", "Cartulina blanca, paquete de 100", "Paquete con 6 piezas"),
    ("SKU-3001", "Pintura vinílica 1 L", "Caja con 12 piezas"),
    ("SKU-3002", "Mochila escolar", "Paquete con 4 piezas"),
]

SUCURSALES = [
    ("Tony Xalapa", "Xalapa, Ver."),
    ("Tony Veracruz Puerto", "Veracruz, Ver."),
    ("Tony Coatzacoalcos", "Coatzacoalcos, Ver."),
    ("Tony Poza Rica", "Poza Rica, Ver."),
    ("Tony Córdoba", "Córdoba, Ver."),
]

PROVEEDORES = [
    "Papelera del Golfo",
    "Oficina y Útiles del Sureste",
    "Arte y Mochilas MX",
]

# (placas, tipo, capacidad en tarimas, capacidad en kg, capacidad en m³)
CAMIONES = [
    ("VER-101-A", "Torton", 14, 9000, 28),
    ("VER-102-B", "Rabón", 8, 5000, 16),
    ("VER-103-C", "Tráiler 53'", 26, 18000, 70),
    ("VER-104-D", "Camioneta 3.5 t", 4, 2500, 8),
]


@contextmanager
def conexion():
    """Abre una conexión; confirma al salir bien y deshace todo si hay error."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sembrar_catalogos(conn):
    if conn.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO productos (sku, nombre, descripcion) VALUES (?, ?, ?)", PRODUCTOS)
    if conn.execute("SELECT COUNT(*) FROM sucursales").fetchone()[0] == 0:
        conn.executemany("INSERT INTO sucursales (nombre, destino) VALUES (?, ?)", SUCURSALES)
    if conn.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0] == 0:
        conn.executemany("INSERT INTO proveedores (nombre) VALUES (?)", [(p,) for p in PROVEEDORES])
    if conn.execute("SELECT COUNT(*) FROM camiones").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO camiones (placas, tipo, capacidad_tarimas, capacidad_kg, capacidad_m3) "
            "VALUES (?, ?, ?, ?, ?)", CAMIONES)
    if conn.execute("SELECT COUNT(*) FROM racks").fetchone()[0] == 0:
        for n in range(1, NUM_RACKS + 1):
            codigo_rack = f"R{n:02d}"
            rack_id = conn.execute(
                "INSERT INTO racks (codigo, niveles, posiciones) VALUES (?, ?, ?)",
                (codigo_rack, NIVELES, POSICIONES)).lastrowid
            for nivel in range(1, NIVELES + 1):
                for posicion in range(1, POSICIONES + 1):
                    conn.execute(
                        "INSERT INTO ubicaciones (rack_id, nivel, posicion, codigo) VALUES (?, ?, ?, ?)",
                        (rack_id, nivel, posicion, f"{codigo_rack}-N{nivel}-P{posicion}"))


# Columnas añadidas después de la primera versión: (tabla, columna, definición)
_COLUMNAS_NUEVAS = [
    ("camiones", "capacidad_kg", "REAL NOT NULL DEFAULT 10000"),
    ("camiones", "capacidad_m3", "REAL NOT NULL DEFAULT 25"),
    ("tarimas", "volumen_m3", "REAL NOT NULL DEFAULT 1.2"),
    ("tarimas", "sucursal_id", "INTEGER REFERENCES sucursales(id)"),
    ("tarimas", "oc_id", "INTEGER REFERENCES ordenes_compra(id)"),
    ("citas", "oc_id", "INTEGER REFERENCES ordenes_compra(id)"),
    ("incidencias", "tipo", "TEXT"),
    ("incidencias", "entrega_id", "INTEGER REFERENCES entregas(id)"),
]


def _migrar(conn):
    """Agrega las columnas nuevas a una base creada con una versión anterior (conserva los datos)."""
    for tabla, columna, definicion in _COLUMNAS_NUEVAS:
        existentes = {f["name"] for f in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
        if existentes and columna not in existentes:
            conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
            if tabla == "camiones":
                for placas, _, _, kg, m3 in CAMIONES:
                    conn.execute(f"UPDATE camiones SET {columna} = ? WHERE placas = ?",
                                 (kg if columna == "capacidad_kg" else m3, placas))


def init_db():
    """Crea las tablas si no existen y carga los catálogos de ejemplo."""
    with conexion() as conn:
        conn.executescript(ESQUEMA)
        _migrar(conn)
        _sembrar_catalogos(conn)


def reset_db():
    """Borra todo y vuelve a crear la base con solo los catálogos."""
    with conexion() as conn:
        for tabla in TABLAS:
            conn.execute(f"DROP TABLE IF EXISTS {tabla}")
    init_db()
