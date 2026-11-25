import { useEffect, useState } from "react";

let operador = "Operador 1";
export const setOperador = (nombre) => { operador = nombre || "Operador 1"; };

async function llamar(metodo, url, cuerpo) {
  const opciones = { method: metodo };
  if (metodo !== "GET") {
    opciones.headers = { "Content-Type": "application/json" };
    opciones.body = JSON.stringify({ operador, ...(cuerpo || {}) });
  }
  let res;
  try {
    res = await fetch(url, opciones);
  } catch {
    throw new Error("No se pudo conectar con el servidor. Revisa que siga corriendo en la Terminal (uvicorn) y vuelve a intentar.");
  }
  let datos = null;
  try { datos = await res.json(); } catch { /* sin cuerpo */ }
  if (!res.ok) {
    let mensaje = datos?.detalle;
    if (!mensaje && Array.isArray(datos?.detail)) {
      mensaje = datos.detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
    }
    if (!mensaje && res.status >= 500) mensaje = "El servidor tuvo un problema. Intenta de nuevo; si se repite, revisa la Terminal donde corre el sistema.";
    throw new Error(mensaje || `No se pudo completar la operación (error ${res.status}).`);
  }
  return datos;
}

export const api = {
  get: (url) => llamar("GET", url),
  post: (url, cuerpo) => llamar("POST", url, cuerpo),
  put: (url, cuerpo) => llamar("PUT", url, cuerpo),
};

/** Reinicia la demo; si el servidor exige clave (versión pública), la pide. Devuelve false si se cancela. */
export async function reiniciarConClave() {
  let consulta = "";
  try {
    const cfg = await api.get("/api/config");
    if (cfg?.reinicio_con_clave) {
      const clave = window.prompt("Clave de reinicio:");
      if (clave === null) return false;
      consulta = "?clave=" + encodeURIComponent(clave);
    }
  } catch { /* servidor sin /api/config: se reinicia sin clave */ }
  await api.post("/api/demo/reiniciar" + consulta);
  return true;
}

/** Carga un endpoint y lo vuelve a pedir cuando cambian las dependencias (o cada `intervalo` ms). */
export function useDatos(url, deps = [], intervalo = 0) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let vivo = true;
    const cargar = () =>
      api.get(url)
        .then((d) => { if (vivo) { setDatos(d); setError(null); } })
        .catch((e) => { if (vivo) setError(e.message); });
    cargar();
    const timer = intervalo ? setInterval(cargar, intervalo) : null;
    return () => { vivo = false; if (timer) clearInterval(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, ...deps]);
  return { datos, error };
}
