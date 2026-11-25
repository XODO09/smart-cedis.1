# Smart CEDIS: prototipo

Sistema web con React (frontend), Python + FastAPI (backend) y SQLite (base de datos). Cubre el flujo completo del CEDIS:
llegada del camión → recepción → ubicación en rack → inventario → embarque → validación → despacho.

## Cómo correrlo

```bash
cd backend
pip install -r requirements.txt
python test_flujo.py                 # prueba el flujo completo
python test_agenda.py                # prueba la agenda y la sincronización (con un Google simulado)
python test_ordenes.py               # prueba OC, bultos, descarga con terminal y salida del camión
python test_extras.py                # incidencias, sugerencias de carga, recepción en sucursal, Excel
uvicorn main:app --reload            # abre http://localhost:8000
```

Con eso ya funciona todo: el frontend viene compilado en `backend/static` y FastAPI lo sirve en la raíz,
así que **no necesitas Node para la demostración**. La documentación de la API queda en http://localhost:8000/docs.

Antes de cada demostración, el botón **Reiniciar demo** (arriba a la derecha) deja la base con 53 tarimas de ejemplo
(equivale a `POST /api/demo/reiniciar`; con `?con_inventario=false` queda vacía).

## Pantallas

| Pestaña | Qué muestra |
|---|---|
| Dashboard | Camiones recibidos, embarques realizados, tarimas almacenadas, capacidad disponible, movimientos pendientes, ocupación por rack |
| Órdenes | Alta de la orden de compra (OC) con su folio de factura único y la factura desglosada por bulto; etiquetas QR de bultos en PDF |
| Recepción | **Terminal portátil** para descargar camiones escaneando bultos contra la OC de la cita; abajo, la recepción manual sin OC (solo pruebas) |
| Inventario | Existencias por producto y listado de tarimas con filtros y búsqueda |
| Embarques | Orden por sucursal, peso/volumen contra el camión (mínimo 90 %), validación de la carga escaneada, confirmación de salida |
| Agenda | Calendario semanal de llegadas de proveedores y entregas a sucursales, con 4 andenes y conexión opcional a Google Calendar |
| Plano | 32 racks con ocupación, detalle por nivel/posición, búsqueda de tarimas y ruta de picking desde el andén |
| Historial | Todos los movimientos con origen, destino y operador |
| Sucursal | Recepción en destino: se escanea la relación (E-000001) y cada bulto; los faltantes quedan como incidencia |
| Incidencias | KPIs de descarga (exactitud, OC con faltantes, tiempos) y detalle de cada rechazo o faltante |

Además, en la barra superior: **Demo guiada** (guion de 11 pasos dentro del sistema), **Excel** (libro completo), y el botón ☀/☾ para tema claro u oscuro.
Las pantallas tienen vista de impresión (Ctrl/Cmd+P); es una versión limpia de la pantalla, no idéntica a los PDF oficiales.

**Sugerencias de carga:** en un embarque que no llega al 90 %, "Sugerir camión y carga" compara los camiones y propone qué tarimas agregar (PEPS).

**Reportes Excel** (`/api/reportes/{inventario|movimientos|ordenes|embarques|citas|incidencias|recepciones|completo}.xlsx`) requieren `openpyxl` (incluido en requirements.txt).

## Códigos QR y PDF

- **Cada tarima** tiene su código (`T-000012`) y **cada embarque** su folio (`E-000001`). El QR contiene ese texto tal cual,
  así que un lector de QR (o la cámara del celular) funciona también como escáner en el cuadro de "Tarimas escaneadas" de la validación.
- Los QR se ven en Embarques (embarque y cada tarima), Inventario y Plano (al elegir una ubicación con tarima).
- **Relación de embarque (PDF):** Embarques → abrir un embarque → *Relación de embarque (PDF)*. Incluye folio y QR, sucursal,
  camión, fechas, operador, tabla de tarimas con su QR y casilla de revisión, resumen por producto con totales, observaciones y firmas.
  Si el embarque aún no sale, el documento indica que es preliminar.
- **Etiquetas de tarima (PDF, 4×6"):** Recepción → *Imprimir etiquetas con QR* (o *Etiquetas* en la lista de recepciones),
  o clic en el QR de una tarima en Inventario.
- Los PDF se abren en una pestaña del navegador; desde ahí se imprimen o se guardan.

Guion con las reglas del CEDIS (el botón **Reiniciar demo** deja 3 OC pendientes con sus citas de llegada):
Órdenes (ver una OC y sus etiquetas; intentar repetir un folio de factura) → Agenda (cita atrasada y andenes) →
Recepción: abrir la cita de la OC → **Simular escaneo** (verde) y **Simular bulto no solicitado** (rojo) → confirmar tarima/film/altura →
Cerrar descarga → Embarques (camión por debajo del 90 % no sale; con carga suficiente sí) → Relación de embarque (PDF con bultos).

Guion corto anterior: Reiniciar demo → Recepción (Cargar ejemplo → Registrar) → Embarques (crear orden →
quitar un código del escaneo para mostrar el error → validar → despachar) → Plano (ruta de picking de otra orden) → Dashboard.

## Reglas de la operación

| Regla | Dónde se cumple |
|---|---|
| Citas por andén de 8:00 a 18:00; descargar toma mínimo 1 hora; no hay dos citas en el mismo andén y horario | Agenda (`agenda.py`) |
| Cada OC lleva un folio de factura propio y no se puede repetir (sin distinguir mayúsculas ni espacios) | Órdenes (`ordenes.crear_orden`; además `UNIQUE` en la base) |
| La factura se desglosa por bulto (producto, piezas, peso y volumen); un bulto lleva un solo producto; no se factura más de lo solicitado | Órdenes |
| Cada bulto lleva etiqueta con QR: bulto, OC, proveedor, sucursal destino, SKU y piezas; el proveedor la descarga y la pega | `GET /api/ordenes/{id}/etiquetas.pdf` |
| Al descargar se escanean los bultos con una terminal portátil; lo no solicitado (otro SKU, excedente, repetido, de otra OC) se reporta y **no se recibe** | Recepción → terminal (`ordenes.escanear_bulto`); los rechazos quedan en la tabla `incidencias` |
| La mercancía conserva la base, lleva film y no rebasa la altura máxima | Casillas obligatorias para cerrar la descarga |
| Los camiones se envían por sucursal y no salen sin cubrir al menos 90 % de su capacidad (peso y volumen) | `services.validar_embarque` |
| Cada embarque genera una Relación de Embarque (impresa y PDF) con los bultos de la sucursal y un QR del embarque | `GET /api/embarques/{id}/relacion.pdf` |

Decisiones que tomé donde la regla dejaba lugar a interpretación (todas se cambian en `database.py` / `ordenes.py`):

- **90 %:** basta con llegar al 90 % en peso **o** en volumen (un camión se llena por el límite que toque primero).
  Si lo quieres en ambos a la vez, cambia `CRITERIO_OCUPACION = "ambos"`. Además, un camión nunca puede pasar del 100 %.
- **Tarimas:** al cerrar la descarga, los bultos escaneados se arman en tarimas de un solo producto y una sola OC,
  con tope de 1,000 kg y 1.8 m³ (`TARIMA_MAX_KG`, `TARIMA_MAX_M3`). Cada tarima hereda la sucursal destino de su OC, así que
  un embarque solo toma tarimas de su sucursal.
- **Capacidades** de los camiones (kg y m³) son valores de ejemplo en `database.py`; ajústalos a los reales.
- **Descarga incompleta:** si se cierra con bultos sin escanear, la OC queda *parcial* y se reportan los faltantes.
- **Horario y duración** aplican también a las entregas a sucursales.
- Si ya tenías un `cedis.db` de una versión anterior, se actualiza solo al arrancar (se conservan tus datos).

## Agenda de llegadas y entregas

La pestaña **Agenda** programa dos tipos de cita en una semana de lunes a domingo:

- **Llegada**: un proveedor trae mercancía; se liga a una **orden de compra** (de ahí salen proveedor y bultos esperados).
- **Entrega**: un embarque sale hacia una sucursal (se puede ligar a un embarque existente).

Cómo se usa: clic en un espacio vacío del calendario (o **+ Nueva cita**) para programar; clic en una cita para ver el detalle.
Cada cita ocupa un **andén** (hay 4) y el sistema no permite dos citas al mismo tiempo en el mismo andén; si hay choque, el
mensaje indica qué andenes están libres. Las citas atrasadas se marcan en rojo y el Dashboard muestra la **agenda de hoy**.

Enlaces con el resto del sistema:

- **Descargar camión (terminal)** abre en Recepción la terminal con los bultos de la OC; al cerrar la descarga, la cita queda *completada*.
- Al **despachar** un embarque, su cita de entrega queda *completada*.
- **Ver embarque** salta a la orden ligada a la cita.

### Conectar Google Calendar (opcional)

Sin configurar nada, la agenda funciona completa dentro del sistema. Para reflejarla en Google Calendar
(sincronización en **un solo sentido**: sistema → Google; lo que edites directamente en Google no regresa al sistema):

1. En [Google Cloud Console](https://console.cloud.google.com) crea un proyecto y habilita la **Google Calendar API**.
2. En *IAM y administración → Cuentas de servicio* crea una cuenta de servicio y, en su pestaña *Claves*,
   genera una llave **JSON**. Guárdala como `backend/google-credentials.json`.
3. En Google Calendar crea un calendario nuevo (por ejemplo «Smart CEDIS»). En *Configuración y uso compartido →
   Compartir con personas* agrega el correo de la cuenta de servicio (termina en `iam.gserviceaccount.com`) con el
   permiso **Hacer cambios en eventos**.
4. En la configuración de ese calendario copia el **ID del calendario** y ponlo en `backend/google_config.json`
   (copia `google_config.example.json`), o define la variable de entorno `GOOGLE_CALENDAR_ID`.
5. Instala las librerías: `pip3 install -r requirements-google.txt` y reinicia el servidor.
6. En la pestaña Agenda abre el panel **Google Calendar** y pulsa **Verificar conexión**; después **Sincronizar ahora**
   sube las citas que ya existían.

A partir de ahí cada cita nueva, editada, cancelada o completada se actualiza sola en Google (color azul para llegadas,
naranja para entregas, gris con ✓ cuando se completan, recordatorio 30 minutos antes). Si Google falla o no hay internet,
**la operación del CEDIS no se detiene**: la cita queda marcada con error y se reintenta con *Sincronizar ahora*.
Nunca subas `google-credentials.json` a un repositorio.

Los datos de demostración (**Reiniciar demo**) crean citas de ejemplo que **no** se suben a Google, para no llenar tu
calendario real; pulsa *Sincronizar ahora* si quieres verlas allá.

## Modificar el frontend

El código fuente está en `frontend/src`. Para recompilarlo:

```bash
cd frontend
npm install
npm run build        # genera backend/static/app.js y app.css
```

## Cambios al diseño original de la base de datos

| Original | Cambio | Motivo |
|---|---|---|
| Racks con "sucursal asignada" | Los racks son físicos, sin sucursal | Cualquier tarima puede ir en cualquier lugar; la sucursal pertenece al embarque |
| Embarques con "tarimas" | Tabla `embarque_tarimas` | Una tarima solo puede estar en un embarque |
| Tarimas sin estado | `recibida → almacenada → asignada → despachada` | Permite descontar inventario al despachar y saber qué está comprometido |
| Recepciones sin proveedor | Tabla `proveedores` | El módulo de recepción registra proveedor |

## Estructura

- `backend/database.py`: esquema, 32 racks × 4 niveles × 6 posiciones (768 ubicaciones) y catálogos de ejemplo
- `backend/services.py`: reglas de negocio (no depende de FastAPI)
- `backend/documentos.py`: códigos QR y PDF (relación de embarque y etiquetas); usa `reportlab`
- `backend/agenda.py`: citas, andenes y sincronización; `backend/gcal.py`: cliente de Google Calendar (opcional)
- `backend/ordenes.py`: órdenes de compra, bultos, descarga con terminal y rechazos
- `backend/test_agenda.py`: pruebas de la agenda con un Google simulado; `backend/test_ordenes.py`: pruebas de OC, descarga y regla del 90 %
- `backend/sucursal.py`: recepción en sucursal; `backend/control.py`: incidencias y KPIs; `backend/reportes.py`: Excel
- `backend/test_extras.py`: pruebas de lo anterior
- `backend/main.py`: endpoints REST y servidor del frontend
- `backend/test_flujo.py`: prueba del flujo de punta a punta
- `backend/static/`: frontend compilado
- `frontend/src/`: código fuente de React (una pantalla por archivo)

## Endpoints principales

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/api/dashboard` | Indicadores del módulo 1 |
| POST | `/api/recepciones` | Registra camión y tarimas; las ubica automáticamente |
| GET | `/api/inventario` | Tarimas en el CEDIS y resumen por SKU |
| GET | `/api/mapa` | Datos del plano: racks, ubicaciones y ocupación |
| POST | `/api/embarques` | Crea la orden para una sucursal y aparta tarimas |
| POST | `/api/embarques/{id}/validar` | Valida camión, capacidad y tarimas escaneadas |
| POST | `/api/embarques/{id}/despachar` | Registra la salida y descuenta inventario |
| GET | `/api/movimientos` | Historial |
| GET | `/api/qr/{codigo}.svg` | Imagen del QR de una tarima o de un embarque |
| GET | `/api/embarques/{id}/relacion.pdf` | Relación de embarque en PDF |
| GET | `/api/recepciones/{id}/etiquetas.pdf` | Etiquetas de todas las tarimas de una recepción |
| GET | `/api/tarimas/{codigo}/etiqueta.pdf` | Etiqueta de una tarima |
| GET/POST | `/api/ordenes` | Lista o crea órdenes de compra (con factura desglosada por bulto) |
| GET | `/api/ordenes/{id}/etiquetas.pdf` | Etiquetas QR de todos los bultos de la OC |
| GET | `/api/descargas/{cita_id}` | Avance de la descarga de una cita |
| POST | `/api/descargas/{cita_id}/escanear` · `/cerrar` | Escaneo de un bulto; cierre de la descarga |
| GET/POST | `/api/citas` | Lista (`desde`, `hasta`, `tipo`, `estado`) o programa citas |
| GET/PUT | `/api/citas/{id}` | Consulta o edita una cita |
| POST | `/api/citas/{id}/cancelar` · `/completar` | Cambia el estado de la cita |
| GET | `/api/agenda/resumen` | Citas de hoy, atrasadas y próximas |
| GET | `/api/google/estado?probar=true` | Estado (y prueba real) de la conexión con Google |
| POST | `/api/google/sincronizar` | Sube a Google las citas pendientes o con error |
| GET | `/api/embarques/{id}/sugerencias` · POST `/agregar` | Camiones sugeridos y tarimas a agregar |
| GET | `/api/sucursal/despachos` · POST `/abrir` | Embarques en camino; abre la recepción |
| GET/POST | `/api/sucursal/{id}` · `/escanear` · `/cerrar` | Avance, escaneo de bulto y cierre con faltantes |
| GET | `/api/incidencias` | KPIs y lista de incidencias |
| GET | `/api/reportes/{nombre}.xlsx` | Reporte en Excel |

## Reglas de negocio incluidas

- Las tarimas se ubican en la primera posición libre, rack por rack.
- Tarimas de 800 kg o más solo van en el nivel 1.
- Si el almacén se llena, la recepción se guarda y las tarimas quedan pendientes de ubicar.
- Los embarques toman las tarimas más antiguas primero (PEPS).
- Un embarque no se valida si el camión no existe, no tiene capacidad o la carga escaneada no coincide.


## Publicarlo en internet (Render)

1. Sube la carpeta del proyecto a un repositorio de GitHub (el frontend compilado ya va incluido).
2. En render.com: **New → Blueprint**, elige el repositorio y confirma. Render lee `render.yaml` y te pide la clave `CEDIS_CLAVE_REINICIO`.
3. Cuando termine, Render te da una dirección `https://smart-cedis-xxxx.onrender.com`.

Variables de entorno que usa el servidor:

| Variable | Para qué sirve |
|---|---|
| `CEDIS_SEMBRAR_DEMO` | Si la base está vacía al arrancar, carga los datos de demostración |
| `CEDIS_CLAVE_REINICIO` | Si está definida, **Reiniciar demo** pide esta clave (evita que un visitante borre la demo) |
| `CEDIS_DB` | Ruta del archivo SQLite (por defecto, `backend/cedis.db`) |
| `TZ` | Zona horaria; la agenda usa la hora local |

En el plan gratuito el servicio se duerme tras unos minutos sin visitas (la primera carga tarda cerca de un minuto) y el disco se borra al reiniciarse: por eso la base se vuelve a sembrar sola.
