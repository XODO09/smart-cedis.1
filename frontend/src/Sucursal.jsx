import { useCallback, useEffect, useRef, useState } from "react";
import { api, useDatos } from "./api.js";
import { useApp, fmtFecha } from "./util.jsx";

const ESTADOS = { sin_recibir: "Por recibir", abierta: "En recepción", cerrada: "Recibido" };

function Terminal({ entregaId, onSalir }) {
  const { refrescar, avisar } = useApp();
  const [est, setEst] = useState(null);
  const [lectura, setLectura] = useState("");
  const [ultimo, setUltimo] = useState(null);
  const [notas, setNotas] = useState("");
  const [resultado, setResultado] = useState(null);
  const [cerrando, setCerrando] = useState(false);
  const campo = useRef(null);

  const cargar = useCallback(() => api.get(`/api/sucursal/${entregaId}`).then(setEst).catch((e) => avisar(e.message, "error")), [entregaId, avisar]);
  useEffect(() => { cargar(); }, [cargar]);
  useEffect(() => { campo.current?.focus(); }, [est, ultimo]);

  const escanear = async (texto) => {
    const valor = (texto ?? lectura).trim();
    if (!valor) return;
    try {
      const r = await api.post(`/api/sucursal/${entregaId}/escanear`, { codigo: valor });
      setUltimo(r);
      setEst((e) => ({ ...e, ...r.progreso }));
    } catch (e) { avisar(e.message, "error"); }
    setLectura("");
  };
  const cerrar = async () => {
    setCerrando(true);
    try {
      const r = await api.post(`/api/sucursal/${entregaId}/cerrar`, { observaciones: notas });
      setResultado(r);
      avisar(r.completa ? "Recepción completa en sucursal." : `Recepción cerrada con ${r.faltantes.length} faltantes.`, r.completa ? "ok" : "error");
      refrescar();
    } catch (e) { avisar(e.message, "error"); }
    setCerrando(false);
  };

  if (!est) return <p className="cargando">Abriendo recepción…</p>;
  const cerrada = est.estado === "cerrada";
  if (resultado || cerrada) {
    const esp = resultado ? resultado.esperados : est.cerrada_esperados;
    const rec = resultado ? resultado.recibidos : est.cerrada_recibidos;
    return (
      <div className="panel resultado-descarga">
        <h3>Recepción en {est.sucursal} · {est.codigo}</h3>
        <p><b>{rec}</b> de <b>{esp}</b> bultos/tarimas recibidos.{esp === rec ? " Entrega completa ✓" : ""}</p>
        {resultado && resultado.faltantes.length > 0 && (
          <ul className="incidencias">{resultado.faltantes.map((f) => <li key={f.codigo}><code>{f.codigo}</code> faltante · {f.detalle}</li>)}</ul>
        )}
        {est.observaciones && <p className="nota">Observaciones: {est.observaciones}</p>}
        <button className="btn-sec" onClick={onSalir}>Terminar</button>
      </div>
    );
  }
  const avance = est.esperados ? Math.round((100 * est.escaneados) / est.esperados) : 0;
  const siguiente = est.pendientes[0];
  return (
    <div className="terminal-grid">
      <div className="terminal">
        <div className="terminal-cab"><span>RECEPCIÓN EN SUCURSAL</span><span>{est.codigo}</span></div>
        <label className="terminal-campo">Escanea cada bulto que baja del camión
          <input ref={campo} value={lectura} placeholder="B-000001" autoComplete="off"
            onChange={(e) => setLectura(e.target.value)} onKeyDown={(e) => e.key === "Enter" && escanear()} />
        </label>
        <div className={`terminal-pantalla ${ultimo ? (ultimo.aceptado ? "ok" : "mal") : ""}`} role="status">
          {!ultimo && <span className="nota">Esperando escaneo…</span>}
          {ultimo?.aceptado && (<><b>✓ Llegó {ultimo.codigo}</b><span>{ultimo.item.detalle}</span></>)}
          {ultimo && !ultimo.aceptado && (<><b>✗ {ultimo.codigo}</b><span>{ultimo.motivo}</span></>)}
        </div>
        <div className="terminal-cuenta"><b>{est.escaneados}</b> / {est.esperados}
          <div className="barra"><div style={{ width: `${avance}%` }} /></div></div>
        <div className="terminal-botones">
          <button className="btn-sec" disabled={!siguiente} onClick={() => escanear(siguiente.codigo)}>Simular escaneo</button>
          <button className="btn-sec" onClick={() => escanear("B-999999")}>Simular bulto ajeno</button>
        </div>
        <button className="btn-sec" onClick={onSalir}>Salir</button>
      </div>
      <div className="panel">
        <h3>{est.sucursal}</h3>
        <p className="nota">Embarque {est.codigo} · camión {est.placas} · salió {fmtFecha(est.fecha_salida)}</p>
        <h4>Pendientes de llegar ({est.pendientes.length})</h4>
        {est.pendientes.length === 0 ? <p className="nota">Ya se escaneó todo lo del embarque.</p> : (
          <div className="chips">{est.pendientes.slice(0, 60).map((p) => <span key={p.codigo} className="chip" title={p.detalle}>{p.codigo}</span>)}
            {est.pendientes.length > 60 && <span className="nota">…y {est.pendientes.length - 60} más</span>}</div>
        )}
        {est.incidencias.length > 0 && (<><h4>Rechazados ({est.incidencias.length})</h4>
          <ul className="incidencias">{est.incidencias.map((i, n) => <li key={n}><code>{i.codigo}</code> {i.motivo}</li>)}</ul></>)}
        <h4>Cerrar recepción</h4>
        <label>Observaciones (opcional)<textarea rows="2" value={notas} onChange={(e) => setNotas(e.target.value)} /></label>
        {est.pendientes.length > 0 && est.escaneados > 0 && <p className="nota">Faltan {est.pendientes.length}: si cierras ahora se reportan como faltantes.</p>}
        <button className="btn" disabled={cerrando || est.escaneados === 0} onClick={cerrar}>{cerrando ? "Cerrando…" : "Cerrar recepción"}</button>
      </div>
    </div>
  );
}

export default function Sucursal() {
  const { version, avisar } = useApp();
  const { datos: lista } = useDatos("/api/sucursal/despachos", [version]);
  const [abierta, setAbierta] = useState(null);
  const [qr, setQr] = useState("");

  const abrir = async (codigo) => {
    try {
      const r = await api.post("/api/sucursal/abrir", { codigo });
      setAbierta(r.entrega_id);
      setQr("");
    } catch (e) { avisar(e.message, "error"); }
  };
  const proximo = (lista || []).find((d) => d.estado !== "cerrada");

  return (
    <section>
      <div className="panel">
        <div className="panel-cab">
          <h3>Recepción en sucursal</h3>
          <span className="nota">Escanea el QR de la relación de embarque que trae el camión.</span>
        </div>
        <div className="acciones-fila">
          <input style={{ maxWidth: 260 }} value={qr} placeholder="E-000001" onChange={(e) => setQr(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && abrir(qr)} />
          <button className="btn-sec" disabled={!qr.trim()} onClick={() => abrir(qr)}>Abrir recepción</button>
          <button className="btn-sec" disabled={!proximo} onClick={() => abrir(proximo.codigo)}>Simular escaneo del QR</button>
        </div>
        {lista && lista.length === 0 && <p className="vacio">Aún no hay embarques despachados. Despacha uno en «Embarques».</p>}
        {lista && lista.length > 0 && (
          <table>
            <thead><tr><th>Embarque</th><th>Sucursal</th><th>Camión</th><th>Salió</th><th>Estado</th><th>Recibido</th><th /></tr></thead>
            <tbody>
              {lista.map((d) => (
                <tr key={d.embarque_id}>
                  <td><b>{d.codigo}</b></td><td>{d.sucursal}</td><td>{d.placas}</td><td>{fmtFecha(d.fecha_salida)}</td>
                  <td><span className={`badge ent-${d.estado}`}>{ESTADOS[d.estado]}</span></td>
                  <td>{d.estado === "cerrada" ? `${d.recibidos}/${d.esperados}` : d.estado === "abierta" ? `${d.escaneados} escaneados` : "—"}</td>
                  <td><button className="btn-sec" onClick={() => abrir(d.codigo)}>{d.estado === "cerrada" ? "Ver" : d.estado === "abierta" ? "Continuar" : "Recibir"}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {abierta && <Terminal key={abierta} entregaId={abierta} onSalir={() => setAbierta(null)} />}
    </section>
  );
}
