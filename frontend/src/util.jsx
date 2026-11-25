import { createContext, useContext } from "react";

export const Contexto = createContext({ version: 0, refrescar: () => {}, avisar: () => {} });
export const useApp = () => useContext(Contexto);

export const fmtFecha = (iso) =>
  iso ? new Date(iso).toLocaleString("es-MX", { dateStyle: "short", timeStyle: "short" }) : "—";

export const fmtNum = (n) => Number(n ?? 0).toLocaleString("es-MX");

// Colores bien separados entre sí (el ámbar queda reservado para la interfaz)
const PALETA = ["#4c9aff", "#3fb97c", "#ef5b5b", "#c58bff", "#2ec4c4", "#ff8a3d", "#e86fb0", "#9acd32", "#7c83ff", "#94a3b8"];
const ordenSku = new Map();

/** Fija el color de cada producto según su posición en el catálogo (mismo SKU, mismo color siempre). */
export function registrarProductos(productos) {
  ordenSku.clear();
  productos.forEach((p, i) => ordenSku.set(p.sku, i));
}

export function colorSku(sku) {
  if (!sku) return "transparent";
  if (ordenSku.has(sku)) return PALETA[ordenSku.get(sku) % PALETA.length];
  let h = 0;
  for (const c of sku) h = (h * 31 + c.charCodeAt(0)) % PALETA.length;
  return PALETA[h];
}

export const COLOR_MOV = {
  recepcion: "#4c9aff",
  almacenamiento: "#2ec4c4",
  asignacion_embarque: "#c58bff",
  despacho: "#3fb97c",
};

const NOMBRES_ESTADO = {
  recibida: "Por ubicar",
  almacenada: "Almacenada",
  asignada: "En embarque",
  despachada: "Despachada",
  pendiente: "Pendiente",
  validado: "Validado",
  despachado: "Despachado",
};

export function Estado({ valor }) {
  return <span className={`badge badge-${valor}`}>{NOMBRES_ESTADO[valor] || valor}</span>;
}

export const rackDeUbicacion = (ubicacion) => (ubicacion ? ubicacion.split("-")[0] : null);

/** Código QR de una tarima (T-000012) o de un embarque (E-000001); la imagen la genera el backend. */
export function QR({ codigo, tam = 80 }) {
  return (
    <img className="qr" src={`/api/qr/${codigo}.svg`} width={tam} height={tam}
      alt={`Código QR ${codigo}`} loading="lazy" />
  );
}

/** Enlace con aspecto de botón que abre un PDF en otra pestaña. */
export function EnlacePdf({ href, children }) {
  return <a className="btn-sec enlace" href={href} target="_blank" rel="noreferrer">{children}</a>;
}

/** Ruta de picking de un embarque: las ubicaciones de sus tarimas en orden de recorrido. */
export function rutaDeEmbarque(embarque) {
  const paradas = (embarque.tarimas || [])
    .filter((t) => t.ubicacion)
    .map((t) => ({ tarima: t.codigo, sku: t.sku, ubicacion: t.ubicacion, rack: rackDeUbicacion(t.ubicacion) }))
    .sort((a, b) => a.ubicacion.localeCompare(b.ubicacion));
  return { titulo: `Picking del embarque ${embarque.codigo} → ${embarque.sucursal}`, paradas };
}

export function Vacio({ texto }) {
  return <div className="vacio">{texto}</div>;
}

/** Enlace con aspecto de botón que descarga un reporte en Excel (.xlsx). */
export function BotonExcel({ nombre, texto = "Exportar a Excel" }) {
  return <a className="btn-sec enlace" href={`/api/reportes/${nombre}.xlsx`} download>{texto}</a>;
}

export function fmtDuracion(seg) {
  if (seg == null) return "—";
  if (seg < 60) return `${seg} s`;
  const m = Math.floor(seg / 60);
  return `${m} min ${seg % 60} s`;
}
