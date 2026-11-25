import { useDatos } from "./api.js";
import { useApp, fmtFecha, fmtNum, COLOR_MOV } from "./util.jsx";

const TIPOS = {
  recepcion: "Recepción",
  almacenamiento: "Almacenamiento",
  asignacion_embarque: "Asignación a embarque",
  despacho: "Despacho",
};

export default function Dashboard({ irA, onRecibir }) {
  const { version } = useApp();
  const { datos: d, error } = useDatos("/api/dashboard", [version], 5000);
  const { datos: mapa } = useDatos("/api/mapa", [version], 5000);
  const { datos: ag } = useDatos("/api/agenda/resumen", [version], 30000);
  const { datos: movs } = useDatos("/api/movimientos?limite=8", [version], 5000);

  if (error) return <p className="error">No se pudo cargar el dashboard: {error}</p>;
  if (!d) return <p className="cargando">Cargando…</p>;

  const p = d.movimientos_pendientes;
  return (
    <section>
      <div className="kpis">
        <div className="kpi">
          <span className="kpi-etiqueta">Camiones recibidos</span>
          <span className="kpi-valor">{fmtNum(d.camiones_recibidos)}</span>
        </div>
        <div className="kpi">
          <span className="kpi-etiqueta">Embarques realizados</span>
          <span className="kpi-valor">{fmtNum(d.embarques_realizados)}</span>
        </div>
        <div className="kpi">
          <span className="kpi-etiqueta">Tarimas almacenadas</span>
          <span className="kpi-valor">{fmtNum(d.tarimas_almacenadas)}</span>
        </div>
        <div className="kpi">
          <span className="kpi-etiqueta">Capacidad disponible</span>
          <span className="kpi-valor">{fmtNum(d.capacidad_disponible)}</span>
          <div className="barra"><div style={{ width: `${d.ocupacion_pct}%` }} /></div>
          <span className="kpi-nota">{d.ocupacion_pct}% ocupado de {fmtNum(d.capacidad_total)} ubicaciones</span>
        </div>
        <div className={`kpi ${p.total ? "kpi-alerta" : ""}`}>
          <span className="kpi-etiqueta">Movimientos pendientes</span>
          <span className="kpi-valor">{fmtNum(p.total)}</span>
          <span className="kpi-nota">
            {p.tarimas_por_ubicar} tarimas por ubicar · {p.embarques_por_despachar} embarques por despachar
          </span>
        </div>
      </div>

      {ag && (
        <div className="panel agenda-hoy">
          <div className="panel-cab">
            <h3>Agenda de hoy</h3>
            <span className="nota">
              {ag.llegadas_hoy} llegadas · {ag.entregas_hoy} entregas pendientes
              {ag.atrasadas > 0 && <b className="atraso"> · {ag.atrasadas} atrasadas</b>}
            </span>
            <button className="btn-sec" onClick={() => irA("agenda")}>Abrir agenda</button>
          </div>
          {ag.hoy.length === 0 ? (
            <p className="vacio">No hay citas para hoy.</p>
          ) : (
            <ul className="lista-agenda">
              {ag.hoy.map((c) => (
                <li key={c.id} className={`${c.atrasada ? "atrasada" : ""} ${c.estado === "completada" ? "hecha" : ""}`}>
                  <span className={`tipo-punto t-${c.tipo}`} />
                  <code>{c.inicio.slice(11, 16)}</code>
                  <span className="lista-titulo">{c.titulo}</span>
                  <span className="nota">Andén {c.anden}</span>
                  {c.atrasada && <b className="atraso">Atrasada</b>}
                  {c.en_curso && <b className="encurso">En curso</b>}
                  {c.estado === "completada" && <span className="nota">✓ completada</span>}
                  {c.estado === "programada" && c.tipo === "llegada" && (
                    <button className="btn-sec" onClick={() => onRecibir(c)}>Recibir</button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="dos-col">
        <div className="panel">
          <h3>Ocupación por rack</h3>
          <div className="tira-racks">
            {(mapa || []).map((r) => {
              const pct = Math.round((100 * r.ocupadas) / r.total);
              return (
                <button key={r.rack} className="mini-rack" onClick={() => irA("plano")}
                  title={`${r.rack}: ${r.ocupadas}/${r.total} ubicaciones (${pct}%)`}>
                  <span className="mini-relleno" style={{ height: `${pct}%` }} />
                  <span className="mini-etiqueta">{r.rack.slice(1)}</span>
                </button>
              );
            })}
          </div>
          <p className="nota">Cada columna es un rack; la altura es su ocupación. Clic para abrir el plano.</p>
        </div>

        <div className="panel">
          <h3>Últimos movimientos</h3>
          {!movs || movs.length === 0 ? (
            <p className="vacio">Todavía no hay movimientos.</p>
          ) : (
            <ul className="lista-mov">
              {movs.map((m) => (
                <li key={m.id}>
                  <span className="punto" style={{ background: COLOR_MOV[m.tipo] }} />
                  <div>
                    <strong>{TIPOS[m.tipo] || m.tipo}</strong> · <code>{m.tarima}</code>
                    <div className="nota">{m.origen} → {m.destino} · {fmtFecha(m.fecha)}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
