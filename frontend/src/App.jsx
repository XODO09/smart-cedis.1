import { useCallback, useEffect, useState } from "react";
import { api, setOperador, reiniciarConClave } from "./api.js";
import { Contexto, registrarProductos } from "./util.jsx";
import Dashboard from "./Dashboard.jsx";
import Recepcion from "./Recepcion.jsx";
import Inventario from "./Inventario.jsx";
import Embarques from "./Embarques.jsx";
import Plano from "./Plano.jsx";
import Historial from "./Historial.jsx";
import Agenda from "./Agenda.jsx";
import Ordenes from "./Ordenes.jsx";
import Incidencias from "./Incidencias.jsx";
import Sucursal from "./Sucursal.jsx";
import DemoGuiada from "./DemoGuiada.jsx";
import { BotonExcel } from "./util.jsx";

const PESTANAS = [
  ["dashboard", "Dashboard"],
  ["ordenes", "Órdenes"],
  ["agenda", "Agenda"],
  ["recepcion", "Recepción"],
  ["inventario", "Inventario"],
  ["embarques", "Embarques"],
  ["sucursal", "Sucursal"],
  ["plano", "Plano"],
  ["incidencias", "Incidencias"],
  ["historial", "Historial"],
];

export default function App() {
  const [pestana, setPestana] = useState(() => location.hash.slice(1) || "dashboard");
  const [version, setVersion] = useState(0);
  const [aviso, setAviso] = useState(null);
  const [ruta, setRuta] = useState(null);
  const [citaRecepcion, setCitaRecepcion] = useState(null);
  const [enfoque, setEnfoque] = useState(null);
  const [demo, setDemo] = useState(false);
  const [tema, setTema] = useState(() => { try { return localStorage.getItem("smart-cedis-tema") || "oscuro"; } catch { return "oscuro"; } });
  useEffect(() => {
    document.documentElement.dataset.tema = tema;
    try { localStorage.setItem("smart-cedis-tema", tema); } catch { /* sin almacenamiento */ }
  }, [tema]);
  const [operador, setNombre] = useState("Operador 1");

  const refrescar = useCallback(() => setVersion((v) => v + 1), []);
  const avisar = useCallback((texto, tipo = "ok") => setAviso({ texto, tipo, id: Date.now() }), []);

  useEffect(() => { location.hash = pestana; }, [pestana]);
  useEffect(() => {
    api.get("/api/productos").then((p) => { registrarProductos(p); refrescar(); }).catch(() => {});
  }, [refrescar]);
  useEffect(() => { setOperador(operador); }, [operador]);
  useEffect(() => {
    if (!aviso) return undefined;
    const t = setTimeout(() => setAviso(null), aviso.tipo === "error" ? 8000 : 4000);
    return () => clearTimeout(t);
  }, [aviso]);

  const recibirCita = (cita) => { setCitaRecepcion(cita); setPestana("recepcion"); };
  const verEmbarque = (id) => { setEnfoque(id); setPestana("embarques"); };
  const irARuta = (r) => { setRuta(r); setPestana("plano"); };

  const reiniciar = async () => {
    if (!window.confirm("Se borrarán todos los datos y se cargará el inventario de demostración. ¿Continuar?")) return;
    try {
      if (!(await reiniciarConClave())) return;
      setRuta(null);
      setCitaRecepcion(null);
      setEnfoque(null);
      avisar("Demostración reiniciada con inventario de ejemplo.", "ok");
      refrescar();
    } catch (e) {
      avisar(e.message, "error");
    }
  };

  return (
    <Contexto.Provider value={{ version, refrescar, avisar }}>
      <header className="cab">
        <div className="marca"><span className="marca-logo">▣</span> SMART <b>CEDIS</b></div>
        <nav>
          {PESTANAS.map(([id, nombre]) => (
            <button key={id} className={pestana === id ? "activa" : ""} onClick={() => setPestana(id)}>{nombre}</button>
          ))}
        </nav>
        <div className="cab-der">
          <button className="btn-sec" onClick={() => setDemo(!demo)}>{demo ? "Cerrar guía" : "Demo guiada"}</button>
          <BotonExcel nombre="completo" texto="Excel" />
          <button className="btn-sec" onClick={() => setTema(tema === "oscuro" ? "claro" : "oscuro")}
            title="Cambiar entre tema oscuro y claro" aria-label="Cambiar tema">{tema === "oscuro" ? "☀" : "☾"}</button>
          <label>Operador <input value={operador} onChange={(e) => setNombre(e.target.value)} /></label>
          <button className="btn-sec" onClick={reiniciar}>Reiniciar demo</button>
        </div>
      </header>

      <main>
        {pestana === "dashboard" && <Dashboard irA={setPestana} onRecibir={recibirCita} />}
        {pestana === "ordenes" && <Ordenes />}
        {pestana === "recepcion" && <Recepcion cita={citaRecepcion} soltarCita={() => setCitaRecepcion(null)} />}
        {pestana === "inventario" && <Inventario />}
        {pestana === "embarques" && <Embarques irARuta={irARuta} abrirId={enfoque} />}
        {pestana === "agenda" && <Agenda onRecibir={recibirCita} onVerEmbarque={verEmbarque} />}
        {pestana === "sucursal" && <Sucursal />}
        {pestana === "incidencias" && <Incidencias />}
        {pestana === "plano" && <Plano ruta={ruta} setRuta={setRuta} />}
        {pestana === "historial" && <Historial />}
      </main>

      <DemoGuiada abierta={demo} cerrar={() => setDemo(false)} irA={setPestana} pestana={pestana} />

      {aviso && (
        <div key={aviso.id} className={`toast toast-${aviso.tipo}`} role="status" onClick={() => setAviso(null)}>
          {aviso.texto}
        </div>
      )}
    </Contexto.Provider>
  );
}
