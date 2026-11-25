import { useCallback, useEffect, useRef, useState } from "react";
import { api, useDatos } from "./api.js";
import { useApp, EnlacePdf, fmtNum } from "./util.jsx";

const hhmm = (iso) => iso.slice(11, 16);
const dia = (iso) => new Date(iso).toLocaleDateString("es-MX", { weekday: "short", day: "numeric", month: "short" });

/** Terminal portátil simulada: el operador escanea cada bulto del camión contra la OC de la cita. */
function Terminal({ citaId, onSalir }) {
  const { refrescar, avisar } = useApp();
  const [est, setEst] = useState(null);
  const [error, setError] = useState(null);
  const [lectura, setLectura] = useState("");
  const [ultimo, setUltimo] = useState(null);
  const [placas, setPlacas] = useState("");
  const [lista, setLista] = useState({ base: false, film: false, altura: false });
  const [cerrando, setCerrando] = useState(false);
  const [resultado, setResultado] = useState(null);
  const campo = useRef(null);

  const cargar = useCallback(async () => {
    try {
      const d = await api.get(`/api/descargas/${citaId}`);
      setEst(d);
      setPlacas((p) => p || d.placas || "");
    } catch (e) { setError(e.message); }
  }, [citaId]);
  useEffect(() => { cargar(); }, [cargar]);
  useEffect(() => { campo.current?.focus(); }, [est, ultimo]);

  const escanear = async (texto) => {
    const valor = (texto ?? lectura).trim();
    if (!valor) return;
    try {
      const r = await api.post(`/api/descargas/${citaId}/escanear`, { codigo: valor });
      setUltimo(r);
      setEst((e) => ({ ...e, ...r.progreso }));
    } catch (e) { avisar(e.message, "error"); }
    setLectura("");
  };

  const cerrar = async () => {
    setCerrando(true);
    try {
      const r = await api.post(`/api/descargas/${citaId}/cerrar`, {
        placas, base_tarima: lista.base, film_seguridad: lista.film, altura_maxima: lista.altura });
      setResultado(r);
      avisar(`Descarga cerrada: ${r.bultos_recibidos} bultos en ${r.tarimas.length} tarimas.`, "ok");
      refrescar();
    } catch (e) { avisar(e.message, "error"); }
    setCerrando(false);
  };

  if (error) return <div className="panel"><p className="error">{error}</p><button className="btn-sec" onClick={onSalir}>Cerrar</button></div>;
  if (!est) return <div className="panel"><p className="cargando">Abriendo terminal…</p></div>;

  if (resultado) {
    return (
      <div className="panel resultado-descarga">
        <h3>Descarga cerrada · {resultado.oc}</h3>
        <p>
          <b>{resultado.bultos_recibidos}</b> bultos recibidos en <b>{resultado.tarimas.length}</b> tarimas
          ({resultado.ubicadas} ubicadas en rack{resultado.sin_ubicar.length ? `, ${resultado.sin_ubicar.length} por ubicar` : ""}).
        </p>
        <div className="chips">{resultado.tarimas.map((t) => <span key={t} className="chip">{t}</span>)}</div>
        {resultado.bultos_faltantes > 0 && (
          <p className="aviso">Faltaron {resultado.bultos_faltantes} bultos: la OC quedó <b>parcial</b>.</p>
        )}
        {resultado.rechazos > 0 && <p className="nota">{resultado.rechazos} escaneos rechazados quedaron reportados como incidencias.</p>}
        <div className="acciones-fila">
          <EnlacePdf href={`/api/recepciones/${resultado.recepcion_id}/etiquetas.pdf`}>Etiquetas de tarima (PDF)</EnlacePdf>
          <button className="btn-sec" onClick={onSalir}>Terminar</button>
        </div>
      </div>
    );
  }

  const avance = est.esperados ? Math.round((100 * est.escaneados) / est.esperados) : 0;
  const siguiente = est.pendientes[0];
  const listo = lista.base && lista.film && lista.altura;

  return (
    <div className="terminal-grid">
      <div className="terminal">
        <div className="terminal-cab">
          <span>TERMINAL PORTÁTIL</span>
          <span>{est.orden.folio}</span>
        </div>
        <label className="terminal-campo">Escanea el QR del bulto
          <input ref={campo} value={lectura} placeholder="B-000001" autoComplete="off"
            onChange={(e) => setLectura(e.target.value)} onKeyDown={(e) => e.key === "Enter" && escanear()} />
        </label>
        <div className={`terminal-pantalla ${ultimo ? (ultimo.aceptado ? "ok" : "mal") : ""}`} role="status">
          {!ultimo && <span className="nota">Esperando escaneo…</span>}
          {ultimo?.aceptado && (<>
            <b>✓ Recibido {ultimo.bulto.codigo}</b>
            <span>{ultimo.bulto.sku} · {ultimo.bulto.producto}</span>
            <span>{ultimo.bulto.piezas} piezas</span>
          </>)}
          {ultimo && !ultimo.aceptado && (<>
            <b>✗ {ultimo.codigo}</b>
            <span>{ultimo.motivo}</span>
          </>)}
        </div>
        <div className="terminal-cuenta">
          <b>{est.escaneados}</b> / {est.esperados} bultos
          <div className="barra"><div style={{ width: `${avance}%` }} /></div>
        </div>
        <div className="terminal-botones">
          <button className="btn-sec" disabled={!siguiente} onClick={() => escanear(siguiente.qr)}>Simular escaneo</button>
          <button className="btn-sec" onClick={() => escanear("B-999999")}>Simular bulto no solicitado</button>
        </div>
        <button className="btn-sec" onClick={onSalir}>Salir de la terminal</button>
      </div>

      <div className="panel">
        <h3>Descarga · {est.orden.proveedor}</h3>
        <p className="nota">
          OC {est.orden.folio} · factura {est.orden.folio_factura} · destino {est.orden.sucursal}
        </p>
        <table>
          <thead><tr><th>Producto</th><th>Solicitadas</th><th>Facturadas</th><th>Bultos</th></tr></thead>
          <tbody>
            {est.por_sku.map((l) => (
              <tr key={l.sku}>
                <td><b>{l.sku}</b><div className="nota">{l.producto}</div></td>
                <td>{fmtNum(l.solicitadas)}</td><td>{fmtNum(l.facturadas)}</td>
                <td>{(l.escaneados || 0) + (l.recibidos || 0)} / {l.bultos}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {est.incidencias.length > 0 && (
          <>
            <h4>Rechazados ({est.incidencias.length})</h4>
            <ul className="incidencias">
              {est.incidencias.map((i, n) => <li key={n}><code>{i.codigo}</code> {i.motivo}</li>)}
            </ul>
          </>
        )}

        <h4>Cerrar descarga</h4>
        <label>Placas del camión<input value={placas} onChange={(e) => setPlacas(e.target.value)} placeholder="TRX-401-A" /></label>
        <label className="check"><input type="checkbox" checked={lista.base} onChange={(e) => setLista({ ...lista, base: e.target.checked })} />
          La mercancía conserva la base de la tarima</label>
        <label className="check"><input type="checkbox" checked={lista.film} onChange={(e) => setLista({ ...lista, film: e.target.checked })} />
          Viene sujeta con film de seguridad</label>
        <label className="check"><input type="checkbox" checked={lista.altura} onChange={(e) => setLista({ ...lista, altura: e.target.checked })} />
          No rebasa la altura máxima</label>
        {est.pendientes.length > 0 && est.escaneados > 0 && (
          <p className="nota">Faltan {est.pendientes.length} bultos por escanear; si cierras ahora, la OC quedará parcial.</p>
        )}
        <button className="btn" disabled={cerrando || est.escaneados === 0 || !listo || !placas.trim()} onClick={cerrar}>
          {cerrando ? "Cerrando…" : `Cerrar descarga (${est.escaneados} bultos)`}
        </button>
      </div>
    </div>
  );
}

/** Citas de llegada con OC listas para descargar; al elegir una se abre la terminal. */
export default function Descargas({ cita }) {
  const { version } = useApp();
  const { datos: citas } = useDatos("/api/citas?tipo=llegada&estado=programada", [version]);
  const [abierta, setAbierta] = useState(cita?.oc_id ? cita.id : null);
  useEffect(() => { if (cita?.oc_id) setAbierta(cita.id); }, [cita]);
  const lista = (citas || []).filter((c) => c.oc_id);

  return (
    <div className="panel descargas">
      <div className="panel-cab">
        <h3>Descarga de camiones</h3>
        <span className="nota">Elige la cita del camión que está en el andén y escanea sus bultos.</span>
      </div>
      {lista.length === 0 ? (
        <p className="vacio">No hay llegadas con orden de compra. Crea una OC en «Órdenes» y agenda su cita.</p>
      ) : (
        <div className="cola">
          {lista.map((c) => (
            <button key={c.id} className={`cola-item ${abierta === c.id ? "on" : ""} ${c.atrasada ? "atrasada" : ""}`}
              onClick={() => setAbierta(abierta === c.id ? null : c.id)}>
              <b>{dia(c.inicio)} · {hhmm(c.inicio)}</b>
              <span>{c.oc_folio} · {c.proveedor}</span>
              <span className="nota">Andén {c.anden}{c.placas ? ` · ${c.placas}` : ""}{c.atrasada ? " · atrasada" : ""}</span>
            </button>
          ))}
        </div>
      )}
      {abierta && <Terminal key={abierta} citaId={abierta} onSalir={() => setAbierta(null)} />}
    </div>
  );
}
