import { useEffect, useMemo, useState } from "react";
import { api, useDatos } from "./api.js";
import { useApp, Vacio, BotonExcel } from "./util.jsx";

const H_INI = 8;   // las citas se agendan de 8:00 a 18:00
const H_FIN = 18;
const ALTO_HORA = 58;
const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const DURACIONES = [60, 90, 120, 180, 240]; // la descarga toma mínimo 1 hora

const dosDig = (n) => String(n).padStart(2, "0");
export const aIso = (d) =>
  `${d.getFullYear()}-${dosDig(d.getMonth() + 1)}-${dosDig(d.getDate())}T${dosDig(d.getHours())}:${dosDig(d.getMinutes())}:00`;
const soloFecha = (d) => aIso(d).slice(0, 10);
const lunesDe = (d) => {
  const r = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  r.setDate(r.getDate() - ((r.getDay() + 6) % 7));
  return r;
};
const sumarDias = (d, n) => { const r = new Date(d); r.setDate(r.getDate() + n); return r; };
const hhmm = (iso) => iso.slice(11, 16);
const minutos = (a, b) => Math.round((new Date(b) - new Date(a)) / 60000);
const etiquetaDuracion = (m) => (m % 60 === 0 ? `${m / 60} h` : m > 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`);
const fmtDia = (d) => d.toLocaleDateString("es-MX", { day: "numeric", month: "short" });
const fmtLargo = (iso) => {
  const t = new Date(iso).toLocaleDateString("es-MX", { weekday: "long", day: "numeric", month: "long" });
  return t.charAt(0).toUpperCase() + t.slice(1);
};

const GOOGLE_TXT = {
  sincronizado: ["En Google Calendar", "ok"],
  pendiente: ["Por actualizar en Google", "aviso"],
  error: ["Error con Google", "error"],
};

/** Reparte en columnas las citas que se traslapan dentro de un mismo día. */
function acomodar(citas) {
  const ordenadas = [...citas].sort((a, b) => a.inicio.localeCompare(b.inicio) || a.id - b.id);
  const salida = [];
  let grupo = [];
  let finGrupo = "";
  const cerrar = () => {
    const cols = Math.max(1, ...grupo.map((g) => g.col + 1));
    grupo.forEach((g) => salida.push({ ...g, cols }));
    grupo = [];
  };
  for (const c of ordenadas) {
    if (grupo.length && c.inicio >= finGrupo) { cerrar(); finGrupo = ""; }
    const usadas = new Set(grupo.filter((g) => g.c.fin > c.inicio).map((g) => g.col));
    let col = 0;
    while (usadas.has(col)) col += 1;
    grupo.push({ c, col });
    if (c.fin > finGrupo) finGrupo = c.fin;
  }
  cerrar();
  return salida;
}

function EstadoGoogle({ cita }) {
  if (!cita.google_estado) return null;
  const [texto, clase] = GOOGLE_TXT[cita.google_estado];
  return <span className={`g-estado g-${clase}`} title={cita.google_error || ""}>{texto}</span>;
}

/* --------------------------------------------------------------- panel de Google */

function PanelGoogle() {
  const { version, refrescar, avisar } = useApp();
  const [abierto, setAbierto] = useState(false);
  const [probando, setProbando] = useState(false);
  const [prueba, setPrueba] = useState(null);
  const [sincronizando, setSincronizando] = useState(false);
  const { datos: g } = useDatos("/api/google/estado", [version]);

  if (!g) return null;
  const r = g.requisitos;
  const verificar = async () => {
    setProbando(true);
    try { setPrueba(await api.get("/api/google/estado?probar=true")); } catch (e) { avisar(e.message, "error"); }
    setProbando(false);
  };
  const sincronizar = async () => {
    setSincronizando(true);
    try {
      const s = await api.post("/api/google/sincronizar");
      avisar(s.errores ? `${s.sincronizadas} sincronizadas, ${s.errores} con error: ${s.primer_error}`
        : `${s.sincronizadas} citas sincronizadas${s.restantes ? `; faltan ${s.restantes} (vuelve a pulsar)` : ""}.`,
      s.errores ? "error" : "ok");
      refrescar();
    } catch (e) { avisar(e.message, "error"); }
    setSincronizando(false);
  };
  const p = prueba || g;
  const paso = (ok, texto) => <li className={ok ? "paso-ok" : "paso-falta"}>{ok ? "✓" : "○"} {texto}</li>;

  return (
    <div className="panel g-panel">
      <button className="g-cab" onClick={() => setAbierto(!abierto)}>
        <span className={`g-punto ${g.configurado ? "on" : ""}`} />
        <strong>Google Calendar</strong>
        <span className="nota">
          {g.configurado
            ? `Conectado${g.pendientes ? ` · ${g.pendientes} por sincronizar` : " · todo al día"}${g.con_error ? ` · ${g.con_error} con error` : ""}`
            : "Sin conectar · la agenda funciona solo dentro del sistema"}
        </span>
        <span className="g-flecha">{abierto ? "▲" : "▼"}</span>
      </button>
      {abierto && (
        <div className="g-cuerpo">
          <ul className="pasos">
            {paso(r.libreria, "Librerías de Google instaladas (pip3 install -r requirements-google.txt)")}
            {paso(r.credenciales, "Archivo de credenciales: backend/google-credentials.json")}
            {paso(r.calendar_id, "ID del calendario en backend/google_config.json")}
          </ul>
          {g.correo_servicio && (
            <p className="nota">Comparte tu calendario con <code>{g.correo_servicio}</code> con permiso «Hacer cambios en eventos».</p>
          )}
          {prueba && (
            <p className={prueba.conectado ? "g-ok" : "error"}>
              {prueba.conectado ? `✓ Conexión correcta con el calendario «${prueba.calendario}».` : prueba.error}
            </p>
          )}
          <div className="g-botones">
            <button className="btn-sec" onClick={verificar} disabled={probando}>
              {probando ? "Verificando…" : "Verificar conexión"}
            </button>
            <button className="btn-sec" onClick={sincronizar} disabled={sincronizando || !g.configurado}>
              {sincronizando ? "Sincronizando…" : "Sincronizar ahora"}
            </button>
          </div>
          <p className="nota">
            La sincronización es en un solo sentido: lo que cambies en el sistema se refleja en Google Calendar
            ({p.zona_horaria}). Los pasos completos están en el README.
          </p>
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------- formulario */

function Formulario({ inicial, cita, onListo, onCancelar }) {
  const { refrescar, avisar } = useApp();
  const { datos: cfg } = useDatos("/api/agenda/config");
  const { datos: proveedores } = useDatos("/api/proveedores");
  const { datos: sucursales } = useDatos("/api/sucursales");
  const { datos: embarques } = useDatos("/api/embarques");
  const { datos: ocs } = useDatos("/api/ordenes");
  const editando = !!cita;
  const base = cita || inicial;
  const [f, setF] = useState({
    tipo: base.tipo || "llegada",
    fecha: base.inicio.slice(0, 10),
    hora: hhmm(base.inicio),
    duracion: cita ? minutos(cita.inicio, cita.fin) : 60,
    anden: base.anden || 1,
    proveedor_id: base.proveedor_id || "",
    sucursal_id: base.sucursal_id || "",
    embarque_id: base.embarque_id || "",
    placas: base.placas || "",
    oc_id: base.oc_id || "",
    tipo_mercancia: base.tipo_mercancia || "",
    tarimas_esperadas: base.tarimas_esperadas || "",
    notas: base.notas || "",
  });
  const [error, setError] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const poner = (campo, valor) => setF((x) => ({ ...x, [campo]: valor }));
  const abiertos = (embarques || []).filter((e) => e.estado !== "despachado");
  const numero = (v) => (v === "" || v == null ? null : Number(v));

  const enviar = async (ev) => {
    ev.preventDefault();
    setError(null);
    setGuardando(true);
    const cuerpo = {
      tipo: f.tipo, inicio: `${f.fecha}T${f.hora}:00`, duracion_min: Number(f.duracion), anden: Number(f.anden),
      proveedor_id: f.tipo === "llegada" ? numero(f.proveedor_id) : null,
      oc_id: f.tipo === "llegada" ? numero(f.oc_id) : null,
      sucursal_id: f.tipo === "entrega" && !f.embarque_id ? numero(f.sucursal_id) : null,
      embarque_id: f.tipo === "entrega" ? numero(f.embarque_id) : null,
      placas: f.placas || null, tipo_mercancia: f.tipo === "llegada" ? f.tipo_mercancia || null : null,
      tarimas_esperadas: f.tipo === "llegada" ? numero(f.tarimas_esperadas) : null, notas: f.notas || null,
    };
    try {
      const r = editando ? await api.put(`/api/citas/${cita.id}`, cuerpo) : await api.post("/api/citas", cuerpo);
      avisar(editando ? "Cita actualizada." : "Cita programada.", "ok");
      refrescar();
      onListo(r);
    } catch (e) {
      setError(e.message);
    }
    setGuardando(false);
  };

  return (
    <form className="panel" onSubmit={enviar}>
      <h3>{editando ? `Editar cita #${cita.id}` : "Nueva cita"}</h3>
      {!editando && (
        <div className="seg">
          {[["llegada", "Llegada de proveedor"], ["entrega", "Entrega a sucursal"]].map(([id, n]) => (
            <button type="button" key={id} className={f.tipo === id ? "on" : ""} onClick={() => poner("tipo", id)}>{n}</button>
          ))}
        </div>
      )}
      <div className="campos">
        <label>Fecha<input type="date" required value={f.fecha} onChange={(e) => poner("fecha", e.target.value)} /></label>
        <label>Hora<input type="time" step="900" required value={f.hora} onChange={(e) => poner("hora", e.target.value)} /></label>
        <label>Duración
          <select value={f.duracion} onChange={(e) => poner("duracion", e.target.value)}>
            {[...new Set([...DURACIONES, Number(f.duracion)])].sort((a, b) => a - b).map((m) =>
              <option key={m} value={m}>{etiquetaDuracion(m)}</option>)}
          </select>
        </label>
      </div>
      <div className="campos campos-2">
        <label>Andén
          <select value={f.anden} onChange={(e) => poner("anden", e.target.value)}>
            {(cfg?.andenes || [1, 2, 3, 4]).map((a) => <option key={a} value={a}>Andén {a}</option>)}
          </select>
        </label>
        <label>Placas del camión
          <input value={f.placas} placeholder="VER-101-A" onChange={(e) => poner("placas", e.target.value)} />
        </label>
      </div>

      {f.tipo === "llegada" ? (
        <>
          <label className="sep">Orden de compra que trae el camión
            <select value={f.oc_id} onChange={(e) => {
              const oc = (ocs || []).find((o) => String(o.id) === e.target.value);
              setF((x) => ({ ...x, oc_id: e.target.value, ...(oc ? { proveedor_id: oc.proveedor_id } : {}) }));
            }}>
              <option value="">Sin OC todavía</option>
              {(ocs || []).filter((o) => o.estado !== "recibida" && (!o.cita_id || o.cita_id === cita?.id)).map((o) => (
                <option key={o.id} value={o.id}>{o.folio} · {o.proveedor} · {o.bultos} bultos</option>
              ))}
            </select>
          </label>
          <label className="sep">Proveedor
            <select value={f.proveedor_id} disabled={!!f.oc_id} onChange={(e) => poner("proveedor_id", e.target.value)}>
              <option value="">Elige…</option>
              {(proveedores || []).map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
            </select>
          </label>
          <div className="campos campos-2">
            <label>Mercancía<input value={f.tipo_mercancia} onChange={(e) => poner("tipo_mercancia", e.target.value)} /></label>
            <label>Tarimas esperadas
              <input type="number" min="1" value={f.tarimas_esperadas} onChange={(e) => poner("tarimas_esperadas", e.target.value)} />
            </label>
          </div>
        </>
      ) : (
        <>
          <label className="sep">Embarque a entregar
            <select value={f.embarque_id} onChange={(e) => poner("embarque_id", e.target.value)}>
              <option value="">Sin embarque todavía (solo sucursal)</option>
              {abiertos.map((e) => <option key={e.id} value={e.id}>{e.codigo} · {e.sucursal} · {e.tarimas} tarimas</option>)}
            </select>
          </label>
          {!f.embarque_id && (
            <label className="sep">Sucursal
              <select value={f.sucursal_id} onChange={(e) => poner("sucursal_id", e.target.value)}>
                <option value="">Elige…</option>
                {(sucursales || []).map((s) => <option key={s.id} value={s.id}>{s.nombre}</option>)}
              </select>
            </label>
          )}
        </>
      )}
      <label className="sep">Notas<textarea rows="2" value={f.notas} onChange={(e) => poner("notas", e.target.value)} /></label>

      {error && <p className="error form-error">{error}</p>}
      <div className="g-botones">
        <button className="btn" disabled={guardando}>{guardando ? "Guardando…" : editando ? "Guardar cambios" : "Programar cita"}</button>
        <button type="button" className="btn-sec" onClick={onCancelar}>Cancelar</button>
      </div>
    </form>
  );
}

/* ----------------------------------------------------------------------- detalle */

function Detalle({ id, onEditar, onRecibir, onVerEmbarque, onCerrar }) {
  const { version, refrescar, avisar } = useApp();
  const { datos: c } = useDatos(`/api/citas/${id}`, [version]);
  if (!c) return <div className="panel"><p className="cargando">Cargando…</p></div>;

  const accion = async (ruta, texto, confirmar) => {
    if (confirmar && !window.confirm(confirmar)) return;
    try { await api.post(`/api/citas/${id}/${ruta}`); avisar(texto, "ok"); refrescar(); } catch (e) { avisar(e.message, "error"); }
  };
  const programada = c.estado === "programada";
  const fila = (k, v) => v ? <div className="dato"><span>{k}</span><b>{v}</b></div> : null;

  return (
    <div className="panel detalle-cita">
      <div className="panel-cab">
        <h3><span className={`tipo-punto t-${c.tipo}`} />{c.titulo}</h3>
        <button className="btn-x" onClick={onCerrar} title="Cerrar">×</button>
      </div>
      <p className="nota cap">{fmtLargo(c.inicio)} · {hhmm(c.inicio)}–{hhmm(c.fin)}</p>
      <div className="estado-cita">
        <span className={`badge cita-${c.atrasada ? "atrasada" : c.estado}`}>
          {c.atrasada ? "Atrasada" : c.en_curso ? "En curso" : c.estado === "programada" ? "Programada" : c.estado === "completada" ? "Completada" : "Cancelada"}
        </span>
        <EstadoGoogle cita={c} />
      </div>
      {fila("Andén", c.anden)}
      {fila("Orden de compra", c.oc_folio && `${c.oc_folio} · factura ${c.oc_factura}`)}
      {fila("Proveedor", c.proveedor)}
      {fila("Sucursal", c.sucursal && `${c.sucursal} · ${c.destino}`)}
      {fila("Embarque", c.embarque_codigo)}
      {fila("Camión", c.placas)}
      {fila("Mercancía", c.tipo_mercancia)}
      {fila("Tarimas esperadas", c.tarimas_esperadas)}
      {fila("Recepción", c.recepcion_id && `#${c.recepcion_id}`)}
      {fila("Notas", c.notas)}
      {c.google_error && <p className="error form-error">{c.google_error}</p>}

      <div className="g-botones acciones">
        {programada && c.tipo === "llegada" && <button className="btn" onClick={() => onRecibir(c)}>{c.oc_id ? "Descargar camión (terminal)" : "Recibir camión"}</button>}
        {c.embarque_id && <button className="btn-sec" onClick={() => onVerEmbarque(c.embarque_id)}>Ver embarque</button>}
        {c.google_link && <a className="btn-sec enlace" href={c.google_link} target="_blank" rel="noreferrer">Abrir en Google Calendar</a>}
        {programada && <button className="btn-sec" onClick={() => onEditar(c)}>Editar</button>}
        {programada && <button className="btn-sec" onClick={() => accion("completar", "Cita marcada como completada.")}>Marcar completada</button>}
        {programada && <button className="btn-sec peligro" onClick={() => accion("cancelar", "Cita cancelada.", "¿Cancelar esta cita?")}>Cancelar cita</button>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ calendario */

export default function Agenda({ onRecibir, onVerEmbarque }) {
  const { version } = useApp();
  const [lunes, setLunes] = useState(() => lunesDe(new Date()));
  const [tipo, setTipo] = useState("");
  const [vista, setVista] = useState(null); // {modo: "ver"|"nueva"|"editar", ...}
  const [ahora, setAhora] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setAhora(new Date()), 60000); return () => clearInterval(t); }, []);

  const hasta = sumarDias(lunes, 7);
  const url = `/api/citas?desde=${aIso(lunes)}&hasta=${aIso(hasta)}${tipo ? `&tipo=${tipo}` : ""}`;
  const { datos: citas, error } = useDatos(url, [version], 30000);

  const dias = useMemo(() => Array.from({ length: 7 }, (_, i) => sumarDias(lunes, i)), [lunes]);
  const porDia = useMemo(() => {
    const m = {};
    (citas || []).forEach((c) => { (m[c.inicio.slice(0, 10)] ||= []).push(c); });
    return m;
  }, [citas]);

  const nueva = (dia, hora) => {
    const h = Math.min(Math.max(hora, H_INI), H_FIN - 1);
    setVista({ modo: "nueva", inicial: { inicio: `${soloFecha(dia)}T${dosDig(Math.floor(h))}:${h % 1 ? "30" : "00"}:00` } });
  };
  const clicRejilla = (e, dia) => {
    if (e.target !== e.currentTarget) return;
    const y = e.clientY - e.currentTarget.getBoundingClientRect().top;
    nueva(dia, H_INI + Math.floor((y / ALTO_HORA) * 2) / 2);
  };

  const hoyTxt = soloFecha(ahora);
  const minAhora = ahora.getHours() * 60 + ahora.getMinutes();
  const esSemanaActual = dias.some((d) => soloFecha(d) === hoyTxt);
  const total = (citas || []).length;

  return (
    <section>
      <PanelGoogle />
      <div className="agenda-grid">
        <div className="panel cal">
          <div className="panel-cab">
            <div className="cal-nav">
              <button className="btn-sec" onClick={() => setLunes(sumarDias(lunes, -7))} aria-label="Semana anterior">‹</button>
              <button className="btn-sec" onClick={() => setLunes(lunesDe(new Date()))}>Hoy</button>
              <button className="btn-sec" onClick={() => setLunes(sumarDias(lunes, 7))} aria-label="Semana siguiente">›</button>
              <h3>{fmtDia(lunes)} – {fmtDia(sumarDias(lunes, 6))}</h3>
            </div>
            <div className="cal-nav">
              <div className="seg seg-chico">
                {[["", "Todas"], ["llegada", "Llegadas"], ["entrega", "Entregas"]].map(([id, n]) => (
                  <button key={id} className={tipo === id ? "on" : ""} onClick={() => setTipo(id)}>{n}</button>
                ))}
              </div>
              <BotonExcel nombre="citas" texto="Excel" />
              <button className="btn" style={{ marginTop: 0 }} onClick={() => nueva(esSemanaActual ? ahora : lunes, Math.max(H_INI, ahora.getHours() + 1))}>+ Nueva cita</button>
            </div>
          </div>
          {error && <p className="error">No se pudo cargar la agenda: {error}</p>}

          <div className="cal-cab">
            <span />
            {dias.map((d) => (
              <span key={d} className={soloFecha(d) === hoyTxt ? "hoy" : ""}>{DIAS[(d.getDay() + 6) % 7]} <b>{d.getDate()}</b></span>
            ))}
          </div>
          <div className="cal-cuerpo" style={{ height: (H_FIN - H_INI) * ALTO_HORA }}>
            <div className="cal-horas">
              {Array.from({ length: H_FIN - H_INI }, (_, i) => <span key={i} style={{ height: ALTO_HORA }}>{dosDig(H_INI + i)}:00</span>)}
            </div>
            {dias.map((d) => {
              const clave = soloFecha(d);
              return (
                <div key={clave} className={`cal-dia ${clave === hoyTxt ? "es-hoy" : ""}`}
                  style={{ backgroundSize: `100% ${ALTO_HORA}px` }} onClick={(e) => clicRejilla(e, d)}>
                  {acomodar(porDia[clave] || []).map(({ c, col, cols }) => {
                    const ini = Math.max(minutos(`${clave}T00:00:00`, c.inicio) / 60, H_INI);
                    const fin = Math.min(minutos(`${clave}T00:00:00`, c.fin) / 60, H_FIN);
                    if (fin <= ini) return null;
                    const alto = (fin - ini) * ALTO_HORA - 2;
                    const clase = `evento t-${c.tipo} ${c.estado === "completada" ? "hecha" : ""} ${c.atrasada ? "atrasada" : ""} ${vista?.id === c.id ? "sel" : ""}`;
                    return (
                      <button key={c.id} className={clase} title={`${c.titulo}\nAndén ${c.anden} · ${hhmm(c.inicio)}–${hhmm(c.fin)}`}
                        style={{ top: (ini - H_INI) * ALTO_HORA + 1, height: alto, left: `${(100 * col) / cols}%`, width: `calc(${100 / cols}% - 3px)` }}
                        onClick={() => setVista({ modo: "ver", id: c.id })}>
                        <b>{hhmm(c.inicio)} · A{c.anden}</b>
                        {alto > 34 && <span>{c.titulo.replace(/^(Llegada|Entrega) · /, "")}</span>}
                        {c.google_estado === "error" && <i className="g-alerta" title="Error con Google">!</i>}
                      </button>
                    );
                  })}
                  {clave === hoyTxt && minAhora >= H_INI * 60 && minAhora <= H_FIN * 60 && (
                    <div className="ahora" style={{ top: ((minAhora - H_INI * 60) / 60) * ALTO_HORA }} />
                  )}
                </div>
              );
            })}
          </div>
          <p className="nota leyenda">
            <span className="tipo-punto t-llegada" /> Llegadas de proveedores &nbsp;
            <span className="tipo-punto t-entrega" /> Entregas a sucursales &nbsp;·&nbsp; Clic en un espacio vacío para programar
            {citas && total === 0 && " · No hay citas esta semana."}
          </p>
        </div>

        <div>
          {!vista && <div className="panel"><Vacio texto="Elige una cita del calendario o programa una nueva." /></div>}
          {vista?.modo === "ver" && (
            <Detalle id={vista.id} onCerrar={() => setVista(null)}
              onEditar={(c) => setVista({ modo: "editar", cita: c })}
              onRecibir={onRecibir} onVerEmbarque={onVerEmbarque} />
          )}
          {vista?.modo === "nueva" && (
            <Formulario key={vista.inicial.inicio} inicial={vista.inicial} onCancelar={() => setVista(null)}
              onListo={(c) => setVista({ modo: "ver", id: c.id })} />
          )}
          {vista?.modo === "editar" && (
            <Formulario key={vista.cita.id} cita={vista.cita} onCancelar={() => setVista({ modo: "ver", id: vista.cita.id })}
              onListo={(c) => setVista({ modo: "ver", id: c.id })} />
          )}
        </div>
      </div>
    </section>
  );
}
