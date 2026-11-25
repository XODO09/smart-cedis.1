import { useEffect, useState } from "react";
import { api, reiniciarConClave } from "./api.js";
import { useApp } from "./util.jsx";

const PASOS = [
  { id: "reinicio", titulo: "Preparar la demo", tab: "dashboard", min: 1,
    hacer: ["Pulsa «Reiniciar ahora»: deja 53 tarimas en rack, 3 órdenes de compra pendientes y citas de hoy y de los próximos días."],
    decir: "Partimos de un CEDIS con inventario y con proveedores por llegar.", accion: "reiniciar" },
  { id: "panorama", titulo: "Panorama del CEDIS", tab: "dashboard", min: 1,
    hacer: ["Muestra los indicadores, la ocupación de los 32 racks y la agenda de hoy (hay una cita atrasada)."],
    decir: "Todo el flujo vive en un solo lugar: llegada, almacenaje, embarque, entrega." },
  { id: "oc", titulo: "Órdenes de compra y factura", tab: "ordenes", min: 2,
    hacer: ["Abre la OC-2026-0101 y muestra el desglose por bulto.", "«Cargar ejemplo», cambia el folio de factura por FAC-A-48211 y crea: el sistema rechaza el folio repetido.", "Abre «Etiquetas de bultos (PDF)»: un QR por caja."],
    decir: "Cada OC lleva una factura única, desglosada por bulto, y el proveedor pega la etiqueta QR." },
  { id: "agenda", titulo: "Agenda de andenes", tab: "agenda", min: 2,
    hacer: ["Muestra la semana, los andenes y el horario de 8:00 a 18:00.", "Programa una cita a las 7:00 o con 30 min para ver las reglas; luego una al mismo andén y hora para ver el choque."],
    decir: "Las citas se ordenan por andén, mínimo 1 hora, sin empalmes. Se sincroniza con Google Calendar." },
  { id: "descarga", titulo: "Descarga con terminal portátil", tab: "recepcion", min: 4,
    hacer: ["Elige la cita de OC-2026-0101.", "«Simular escaneo» varias veces (verde) y «Simular bulto no solicitado» (rojo).", "Escanea hasta completar, marca tarima/film/altura y cierra la descarga."],
    decir: "No se recibe mercancía no solicitada: se reporta y el bulto no entra." },
  { id: "incidencias", titulo: "Control de incidencias", tab: "incidencias", min: 1,
    hacer: ["Muestra la exactitud de descarga y el rechazo registrado con su motivo."],
    decir: "Cada rechazo queda trazado: qué bulto, por qué y en qué OC." },
  { id: "embarque", titulo: "Embarque con la regla del 90 %", tab: "embarques", min: 4,
    hacer: ["Crea un embarque a Sucursal Xalapa de SKU-1001, 2 tarimas.", "Elige VER-101-A y valida: el camión no sale (menos del 90 %).", "«Sugerir camión y carga» → «Agregar N y usar» → valida y despacha."],
    decir: "El camión solo sale con al menos 90 % de capacidad; el sistema propone cómo completarlo." },
  { id: "relacion", titulo: "Relación de embarque", tab: "embarques", min: 1,
    hacer: ["Abre «Relación de embarque (PDF)»: bultos agrupados por sucursal, QR del embarque y firmas."],
    decir: "El documento impreso viaja con el camión y su QR abre la recepción en destino." },
  { id: "sucursal", titulo: "Recepción en la sucursal", tab: "sucursal", min: 3,
    hacer: ["«Simular escaneo del QR» del embarque despachado.", "Escanea casi todos los bultos, prueba «Simular bulto ajeno» y cierra dejando uno sin escanear."],
    decir: "La sucursal confirma bulto por bulto; lo que no llega queda como faltante." },
  { id: "cierre", titulo: "Cierre: incidencias y reportes", tab: "incidencias", min: 2,
    hacer: ["Muestra el faltante en sucursal y la exactitud.", "«Exportar a Excel» para llevarse los datos."],
    decir: "De la orden de compra a la sucursal, todo es trazable y exportable." },
];

const GUARDA = "smart-cedis-demo";
const leer = () => { try { return JSON.parse(localStorage.getItem(GUARDA)) || {}; } catch { return {}; } };
const guardar = (v) => { try { localStorage.setItem(GUARDA, JSON.stringify(v)); } catch { /* sin almacenamiento */ } };

export default function DemoGuiada({ abierta, cerrar, irA, pestana }) {
  const { refrescar, avisar } = useApp();
  const [estado, setEstado] = useState(() => ({ paso: 0, hechos: [], ...leer() }));
  useEffect(() => { guardar(estado); }, [estado]);
  if (!abierta) return null;

  const paso = PASOS[estado.paso];
  const marcar = (id) => setEstado((e) => ({ ...e, hechos: e.hechos.includes(id) ? e.hechos.filter((x) => x !== id) : [...e.hechos, id] }));
  const ir = (n) => {
    const i = Math.min(Math.max(n, 0), PASOS.length - 1);
    setEstado((e) => ({ ...e, paso: i }));
    irA(PASOS[i].tab);
  };
  const reiniciar = async () => {
    if (!window.confirm("Se borrarán todos los datos y se cargará la demostración. ¿Continuar?")) return;
    try { if (!(await reiniciarConClave())) return; avisar("Demostración reiniciada.", "ok"); refrescar(); marcar("reinicio"); }
    catch (e) { avisar(e.message, "error"); }
  };
  const total = PASOS.reduce((t, p) => t + p.min, 0);

  return (
    <aside className="demo" aria-label="Demo guiada">
      <div className="demo-cab">
        <b>Demo guiada</b>
        <span className="nota">≈ {total} min · paso {estado.paso + 1} de {PASOS.length}</span>
        <button className="btn-x" onClick={cerrar} title="Cerrar">×</button>
      </div>
      <div className="demo-puntos">
        {PASOS.map((p, i) => (
          <button key={p.id} className={`${i === estado.paso ? "act" : ""} ${estado.hechos.includes(p.id) ? "ok" : ""}`}
            title={p.titulo} onClick={() => ir(i)}>{i + 1}</button>
        ))}
      </div>
      <h3>{paso.titulo} <span className="nota">· {paso.min} min</span></h3>
      <h4>Qué hacer</h4>
      <ol className="demo-lista">{paso.hacer.map((h, i) => <li key={i}>{h}</li>)}</ol>
      <h4>Qué decir</h4>
      <p className="demo-decir">“{paso.decir}”</p>
      <div className="acciones-fila">
        {paso.accion === "reiniciar" && <button className="btn" style={{ marginTop: 0 }} onClick={reiniciar}>Reiniciar ahora</button>}
        {pestana !== paso.tab && <button className="btn-sec" onClick={() => irA(paso.tab)}>Ir a esta pantalla</button>}
        <label className="check" style={{ marginTop: 0 }}>
          <input type="checkbox" checked={estado.hechos.includes(paso.id)} onChange={() => marcar(paso.id)} /> Listo
        </label>
      </div>
      <div className="demo-nav">
        <button className="btn-sec" disabled={estado.paso === 0} onClick={() => ir(estado.paso - 1)}>‹ Anterior</button>
        <button className="btn" style={{ marginTop: 0 }} disabled={estado.paso === PASOS.length - 1}
          onClick={() => { if (!estado.hechos.includes(paso.id)) marcar(paso.id); ir(estado.paso + 1); }}>Siguiente ›</button>
      </div>
      <button className="btn-sec demo-reset" onClick={() => setEstado({ paso: 0, hechos: [] })}>Empezar de nuevo</button>
    </aside>
  );
}
