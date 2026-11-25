import { useMemo, useState } from "react";
import { useDatos } from "./api.js";
import { useApp, colorSku, rutaDeEmbarque, Estado, QR, EnlacePdf } from "./util.jsx";

// --- Geometría del plano: 4 filas x 8 columnas de racks, 2 pasillos y un andén ---
const W = 86, H = 46, GX = 14, LANE = 56, TOP = 14, CORR = 34, GAP = 28;
const COLS = 8;
const ROW_Y = [TOP, TOP + H + CORR, TOP + 2 * H + CORR + GAP, TOP + 3 * H + 2 * CORR + GAP];
const CORR_Y = [ROW_Y[0] + H + CORR / 2, ROW_Y[2] + H + CORR / 2]; // pasillo A (filas 0-1) y B (filas 2-3)
const DOCK_Y = ROW_Y[3] + H + 26;
const ANCHO = LANE + GX + COLS * (W + GX);
const ALTO = DOCK_Y + 52;
const LANE_X = LANE / 2;

function geometria(numero) {
  const fila = Math.floor((numero - 1) / COLS);
  const col = (numero - 1) % COLS;
  const x = LANE + GX + col * (W + GX);
  const y = ROW_Y[fila];
  const pasillo = fila <= 1 ? 0 : 1;
  const arribaDelPasillo = fila === 0 || fila === 2; // el rack queda encima del pasillo
  return { x, y, cx: x + W / 2, corrY: CORR_Y[pasillo], bordeY: arribaDelPasillo ? y + H : y };
}

/** Puntos del recorrido: andén → pasillo lateral → pasillo de cada rack → de regreso al andén. */
function trazar(racks) {
  const pts = [[LANE_X, DOCK_Y]];
  let actual = { x: LANE_X, y: DOCK_Y, pasillo: null };
  const ir = (x, y) => pts.push([x, y]);
  for (const r of racks) {
    const g = geometria(r);
    if (actual.pasillo !== g.corrY) {
      if (actual.x !== LANE_X) ir(LANE_X, actual.y);
      ir(LANE_X, g.corrY);
    }
    ir(g.cx, g.corrY);
    ir(g.cx, g.bordeY);
    ir(g.cx, g.corrY);
    actual = { x: g.cx, y: g.corrY, pasillo: g.corrY };
  }
  ir(LANE_X, actual.y);
  ir(LANE_X, DOCK_Y);
  return pts;
}

export default function Plano({ ruta, setRuta }) {
  const { version } = useApp();
  const { datos: mapa, error } = useDatos("/api/mapa", [version], 5000);
  const { datos: embarques } = useDatos("/api/embarques", [version]);
  const [seleccion, setSeleccion] = useState(null);
  const [celda, setCelda] = useState(null);
  const [buscar, setBuscar] = useState("");
  const [msg, setMsg] = useState("");

  const racksRuta = useMemo(() => {
    const vistos = [];
    for (const p of ruta?.paradas || []) {
      const n = Number(p.rack.slice(1));
      if (!vistos.includes(n)) vistos.push(n);
    }
    return vistos;
  }, [ruta]);
  const puntos = useMemo(() => (racksRuta.length ? trazar(racksRuta) : []), [racksRuta]);
  const ubicacionesRuta = new Set((ruta?.paradas || []).map((p) => p.ubicacion));

  if (error) return <p className="error">No se pudo cargar el plano: {error}</p>;
  if (!mapa) return <p className="cargando">Cargando…</p>;

  const rackSel = mapa.find((r) => r.rack === seleccion);

  const buscarTarima = (e) => {
    e.preventDefault();
    const q = buscar.trim().toUpperCase();
    if (!q) return;
    for (const r of mapa) {
      const u = r.ubicaciones.find((x) => x.tarima === q);
      if (u) {
        setSeleccion(r.rack);
        setCelda(u);
        setRuta({ titulo: `Ruta a la tarima ${q}`, paradas: [{ tarima: q, sku: u.sku, ubicacion: u.codigo, rack: r.rack }] });
        setMsg("");
        return;
      }
    }
    setMsg(`La tarima ${q} no está en ningún rack (¿ya salió o no se ha ubicado?).`);
  };

  const elegirEmbarque = async (id) => {
    if (!id) return setRuta(null);
    const res = await fetch(`/api/embarques/${id}`);
    const e = await res.json();
    setRuta(rutaDeEmbarque(e));
  };

  return (
    <section>
      <div className="barra-plano">
        <form onSubmit={buscarTarima} className="filtros">
          <input placeholder="Buscar tarima (ej. T-000012)" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
          <button className="btn-sec">Localizar</button>
        </form>
        <label className="filtros">Ruta de picking:
          <select value="" onChange={(e) => elegirEmbarque(e.target.value)}>
            <option value="">Elige un embarque…</option>
            {(embarques || []).filter((e) => e.estado !== "despachado").map((e) => (
              <option key={e.id} value={e.id}>{e.codigo} · {e.sucursal} ({e.tarimas} tarimas)</option>
            ))}
          </select>
        </label>
        {ruta && <button className="btn-sec" onClick={() => setRuta(null)}>Quitar ruta</button>}
      </div>
      {msg && <p className="error">{msg}</p>}

      <div className="plano-grid">
        <div className="panel plano">
          <svg viewBox={`0 0 ${ANCHO} ${ALTO}`} role="img" aria-label="Plano del CEDIS">
            <rect x="0" y="0" width={ANCHO} height={ALTO} className="piso" />
            {CORR_Y.map((y) => (
              <rect key={y} x={LANE} y={y - CORR / 2} width={ANCHO - LANE} height={CORR} className="pasillo" />
            ))}
            <rect x="0" y={TOP} width={LANE} height={DOCK_Y - TOP} className="pasillo" />
            <rect x="6" y={DOCK_Y} width={LANE + 3 * (W + GX)} height="40" rx="4" className="anden" />
            <text x={LANE + 3 * (W + GX) / 2 + 6} y={DOCK_Y + 24} className="anden-txt" textAnchor="middle">
              ANDÉN DE RECEPCIÓN Y EMBARQUE
            </text>

            {mapa.map((r) => {
              const n = Number(r.rack.slice(1));
              const g = geometria(n);
              const pct = r.ocupadas / r.total;
              const enRuta = racksRuta.includes(n);
              return (
                <g key={r.rack} className={`rack ${seleccion === r.rack ? "sel" : ""} ${enRuta ? "en-ruta" : ""}`}
                  onClick={() => { setSeleccion(r.rack); setCelda(null); }}>
                  <rect x={g.x} y={g.y} width={W} height={H} rx="4" className="rack-caja" />
                  <rect x={g.x} y={g.y + H - 5} width={W * pct} height="5" rx="2" className="rack-nivel" />
                  <text x={g.cx} y={g.y + 20} textAnchor="middle" className="rack-nombre">{r.rack}</text>
                  <text x={g.cx} y={g.y + 34} textAnchor="middle" className="rack-pct">
                    {r.ocupadas}/{r.total}
                  </text>
                </g>
              );
            })}

            {puntos.length > 0 && (
              <>
                <polyline points={puntos.map((p) => p.join(",")).join(" ")} className="ruta" />
                {racksRuta.map((n, i) => {
                  const g = geometria(n);
                  return (
                    <g key={n}>
                      <circle cx={g.cx} cy={g.bordeY} r="9" className="parada" />
                      <text x={g.cx} y={g.bordeY + 4} textAnchor="middle" className="parada-txt">{i + 1}</text>
                    </g>
                  );
                })}
              </>
            )}
          </svg>
          <p className="nota">
            Clic en un rack para ver sus niveles. La barra inferior de cada rack muestra su ocupación.
          </p>
        </div>

        <div className="lateral">
          {ruta && (
            <div className="panel">
              <h3>{ruta.titulo}</h3>
              {ruta.paradas.length === 0 ? (
                <p className="vacio">Este embarque no tiene tarimas ubicadas.</p>
              ) : (
                <ol className="pick">
                  {ruta.paradas.map((p) => (
                    <li key={p.tarima}>
                      <span className="punto" style={{ background: colorSku(p.sku) }} />
                      <code>{p.tarima}</code> en <strong>{p.ubicacion}</strong>
                    </li>
                  ))}
                </ol>
              )}
              <p className="nota">Recorrido: {racksRuta.map((n) => `R${String(n).padStart(2, "0")}`).join(" → ") || "—"}</p>
            </div>
          )}

          <div className="panel">
            {!rackSel ? (
              <p className="vacio">Elige un rack del plano para ver su contenido.</p>
            ) : (
              <>
                <h3>Rack {rackSel.rack} <span className="nota">{rackSel.ocupadas}/{rackSel.total} ocupadas</span></h3>
                <div className="niveles">
                  {Array.from({ length: rackSel.niveles }, (_, i) => rackSel.niveles - i).map((nivel) => (
                    <div className="nivel" key={nivel}>
                      <span className="nivel-etq">N{nivel}</span>
                      {rackSel.ubicaciones.filter((u) => u.nivel === nivel).map((u) => (
                        <button key={u.codigo}
                          className={`celda ${u.tarima ? "llena" : ""} ${u.estado === "asignada" ? "asignada" : ""} ${ubicacionesRuta.has(u.codigo) ? "destino" : ""} ${celda?.codigo === u.codigo ? "sel" : ""}`}
                          style={u.tarima ? { background: colorSku(u.sku) } : undefined}
                          title={u.tarima ? `${u.tarima} · ${u.sku}` : `${u.codigo} libre`}
                          onClick={() => setCelda(u)}>
                          {u.tarima ? u.tarima.slice(-3) : ""}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
                {celda && (
                  <div className="celda-info">
                    <strong>{celda.codigo}</strong>
                    {celda.tarima ? (
                      <div className="celda-tarima">
                        <QR codigo={celda.tarima} tam={92} />
                        <div>
                          <div><code>{celda.tarima}</code> · {celda.sku}</div>
                          <div style={{ margin: "6px 0 10px" }}><Estado valor={celda.estado} /></div>
                          <EnlacePdf href={`/api/tarimas/${celda.tarima}/etiqueta.pdf`}>Imprimir etiqueta</EnlacePdf>
                        </div>
                      </div>
                    ) : (
                      <div className="nota">Ubicación libre</div>
                    )}
                  </div>
                )}
                <div className="leyenda">
                  <span><i className="celda-mini" /> libre</span>
                  <span><i className="celda-mini llena" /> almacenada</span>
                  <span><i className="celda-mini llena asignada" /> en embarque</span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
