import { useEffect, useState } from "react";
import { api, useDatos } from "./api.js";
import { useApp, Estado, Vacio, QR, EnlacePdf, fmtFecha, rutaDeEmbarque, BotonExcel } from "./util.jsx";

let contador = 0;
const nuevoItem = () => ({ id: ++contador, sku: "", tarimas: 1 });

const NOMBRE_SUG = { cumple: "Listo para salir", agregar: "Completar carga", insuficiente: "Sin tarimas suficientes", excede: "No cabe" };

/** Qué camión conviene y qué tarimas faltan para llegar al mínimo de ocupación. */
function Sugerencias({ id, onUsar }) {
  const { version, refrescar, avisar } = useApp();
  const { datos: s, error } = useDatos(`/api/embarques/${id}/sugerencias`, [version]);
  const [ocupado, setOcupado] = useState(false);
  if (error) return <p className="error">{error}</p>;
  if (!s) return <p className="cargando">Calculando…</p>;

  const agregar = async (c) => {
    setOcupado(true);
    try {
      await api.post(`/api/embarques/${id}/agregar`, { codigos: c.agregar.map((t) => t.codigo) });
      avisar(`Se agregaron ${c.agregar.length} tarimas. Camión sugerido: ${c.placas}.`, "ok");
      onUsar(c.placas);
      refrescar();
    } catch (err) { avisar(err.message, "error"); }
    setOcupado(false);
  };
  return (
    <div className="sugerencias">
      <p className="nota">
        Carga actual: {s.tarimas} tarimas · {s.peso_kg.toLocaleString("es-MX")} kg · {s.volumen_m3} m³. El camión debe cubrir al menos el {s.minimo_pct}%.
      </p>
      <table>
        <thead><tr><th>Camión</th><th>Ocupación actual</th><th>Resultado</th><th /></tr></thead>
        <tbody>
          {s.camiones.map((c) => (
            <tr key={c.placas}>
              <td><b>{c.placas}</b><div className="nota">{c.tipo} · {c.capacidad_kg.toLocaleString("es-MX")} kg</div></td>
              <td>{c.peso_pct}% peso · {c.volumen_pct}% vol.</td>
              <td><span className={`sug sug-${c.estado}`}>{NOMBRE_SUG[c.estado]}</span><div className="nota">{c.nota}</div>
                {c.agregar.length > 0 && <div className="nota">+ {c.agregar.map((t) => t.codigo).join(", ")}</div>}</td>
              <td>
                {c.estado === "cumple" && <button className="btn-sec" onClick={() => onUsar(c.placas)}>Usar este camión</button>}
                {c.estado === "agregar" && <button className="btn-sec" disabled={ocupado} onClick={() => agregar(c)}>Agregar {c.agregar.length} y usar</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Detalle({ id, irARuta }) {
  const { version, refrescar, avisar } = useApp();
  const { datos: e } = useDatos(`/api/embarques/${id}`, [version]);
  const { datos: camiones } = useDatos("/api/camiones");
  const [placas, setPlacas] = useState("");
  const [codigos, setCodigos] = useState(null);
  const [ocupado, setOcupado] = useState(false);
  const [verSug, setVerSug] = useState(false);

  if (!e) return <p className="cargando">Cargando…</p>;

  const cam = (camiones || []).find((c) => c.placas === (placas || e.placas || "").trim().toUpperCase());
  const ocu = e.ocupacion || (cam && {
    peso_pct: Math.round((1000 * e.peso_kg) / cam.capacidad_kg) / 10,
    volumen_pct: Math.round((1000 * e.volumen_m3) / cam.capacidad_m3) / 10,
    minimo_pct: 90, cumple_minimo: Math.max(e.peso_kg / cam.capacidad_kg, e.volumen_m3 / cam.capacidad_m3) >= 0.9,
  });
  const codigosEsperados = e.tarimas.map((t) => t.codigo).join("\n");
  const texto = codigos ?? codigosEsperados;

  const ejecutar = async (accion, cuerpo, mensaje) => {
    setOcupado(true);
    try {
      await api.post(`/api/embarques/${id}/${accion}`, cuerpo);
      avisar(mensaje, "ok");
      refrescar();
    } catch (err) {
      avisar(err.message, "error");
    } finally {
      setOcupado(false);
    }
  };

  const validar = () => {
    const lista = texto.split(/[\s,;]+/).map((c) => c.trim().toUpperCase()).filter(Boolean);
    ejecutar("validar", { placas_camion: placas, codigos_escaneados: lista.length ? lista : null },
      `Embarque ${e.codigo} validado.`);
  };

  return (
    <div className="detalle">
      <div className="emb-id">
        <QR codigo={e.codigo} tam={104} />
        <div>
          <div className="folio">{e.codigo}</div>
          <div className="nota">
            {e.sucursal} · {e.destino}<br />
            Creado {fmtFecha(e.fecha_creacion)}
            {e.fecha_salida && ` · salió ${fmtFecha(e.fecha_salida)} en ${e.placas}`}
          </div>
          <EnlacePdf href={`/api/embarques/${id}/relacion.pdf`}>Relación de embarque (PDF)</EnlacePdf>
        </div>
      </div>

      <div className="carga">
        <span><b>{e.peso_kg.toLocaleString("es-MX")} kg</b> · <b>{e.volumen_m3} m³</b> · {e.tarimas.length} tarimas{e.bultos.length ? ` · ${e.bultos.length} bultos` : ""}</span>
        {ocu && (
          <span className={`ocupacion ${ocu.cumple_minimo ? "ok" : "falta"}`}>
            Camión {e.placas || placas}: {ocu.peso_pct}% del peso · {ocu.volumen_pct}% del volumen
            {ocu.cumple_minimo ? " ✓ cumple" : ` · mínimo ${ocu.minimo_pct}% para salir`}
          </span>
        )}
      </div>
      <table>
        <thead><tr><th>Tarima</th><th>Producto</th><th>Ubicación</th><th>Estado</th><th>QR</th></tr></thead>
        <tbody>
          {e.tarimas.map((t) => (
            <tr key={t.codigo}>
              <td><code>{t.codigo}</code></td><td>{t.sku}</td><td>{t.ubicacion || t.origen || "—"}</td>
              <td><Estado valor={t.estado} /></td>
              <td><QR codigo={t.codigo} tam={40} /></td>
            </tr>
          ))}
        </tbody>
      </table>

      {e.estado === "pendiente" && (
        <div className="acciones">
          <button className="btn-sec" onClick={() => irARuta(rutaDeEmbarque(e))}>Ver ruta de picking en el plano</button>
          <button className="btn-sec" onClick={() => setVerSug(!verSug)}>{verSug ? "Ocultar sugerencias" : "Sugerir camión y carga"}</button>
          {verSug && <Sugerencias id={id} onUsar={(p) => setPlacas(p)} />}
          <h4>Validar carga</h4>
          <div className="campos campos-2">
            <label>Camión asignado
              <select value={placas} onChange={(ev) => setPlacas(ev.target.value)}>
                <option value="">Elige…</option>
                {(camiones || []).map((c) => (
                  <option key={c.id} value={c.placas}>{c.placas} · {c.tipo} ({c.capacidad_tarimas} tarimas, {c.capacidad_kg.toLocaleString("es-MX")} kg)</option>
                ))}
              </select>
            </label>
            <label>Tarimas escaneadas (una por línea)
              <textarea rows={Math.min(8, e.tarimas.length + 1)} value={texto}
                onChange={(ev) => setCodigos(ev.target.value)} />
            </label>
          </div>
          <p className="nota">
            Para simular el escaneo ya aparecen todas las tarimas de la orden. Quita o agrega un código
            para ver cómo el sistema detecta que la carga no coincide.
          </p>
          <button className="btn" disabled={ocupado || !placas} onClick={validar}>Validar carga</button>
        </div>
      )}

      {e.estado === "validado" && (
        <div className="acciones">
          <button className="btn-sec" onClick={() => irARuta(rutaDeEmbarque(e))}>Ver ruta de picking en el plano</button>
          <p className="nota">Carga validada en el camión {e.placas}. Al despachar se descuenta el inventario.</p>
          <button className="btn" disabled={ocupado}
            onClick={() => ejecutar("despachar", {}, `Embarque ${e.codigo} despachado. Ya puedes imprimir la relación.`)}>
            Confirmar salida del camión
          </button>
        </div>
      )}
    </div>
  );
}

export default function Embarques({ irARuta, abrirId = null }) {
  const { version, refrescar, avisar } = useApp();
  const { datos: sucursales } = useDatos("/api/sucursales");
  const { datos: inv } = useDatos("/api/inventario", [version]);
  const { datos: embarques } = useDatos("/api/embarques", [version]);

  const [sucursalId, setSucursalId] = useState("");
  const [items, setItems] = useState([nuevoItem()]);
  const [enviando, setEnviando] = useState(false);
  const [abierto, setAbierto] = useState(abrirId);
  useEffect(() => { if (abrirId) setAbierto(abrirId); }, [abrirId]);

  const disponibles = Object.fromEntries((inv?.resumen || []).map((r) => [r.sku, r.disponibles]));
  const conStock = (inv?.resumen || []).filter((r) => r.disponibles > 0);

  const cambiar = (id, campo, valor) =>
    setItems((is) => is.map((i) => (i.id === id ? { ...i, [campo]: valor } : i)));

  const crear = async (ev) => {
    ev.preventDefault();
    if (!sucursalId) return avisar("Elige la sucursal de destino.", "error");
    if (items.some((i) => !i.sku)) return avisar("Elige el producto en todas las líneas.", "error");
    setEnviando(true);
    try {
      const r = await api.post("/api/embarques", {
        sucursal_id: Number(sucursalId),
        items: items.map((i) => ({ sku: i.sku, tarimas: Number(i.tarimas) })),
      });
      avisar(`Embarque ${r.codigo} creado con ${r.tarimas.length} tarimas.`, "ok");
      setItems([nuevoItem()]);
      setAbierto(r.embarque_id);
      refrescar();
    } catch (err) {
      avisar(err.message, "error");
    } finally {
      setEnviando(false);
    }
  };

  return (
    <section className="dos-col dos-col-form">
      <form className="panel" onSubmit={crear}>
        <h3>Solicitud de embarque</h3>
        <label>Sucursal de destino
          <select value={sucursalId} onChange={(e) => setSucursalId(e.target.value)}>
            <option value="">Elige…</option>
            {(sucursales || []).map((s) => <option key={s.id} value={s.id}>{s.nombre} · {s.destino}</option>)}
          </select>
        </label>

        <h4>Productos solicitados</h4>
        {conStock.length === 0 && inv && <Vacio texto="No hay tarimas disponibles. Registra una recepción primero." />}
        {items.map((i) => (
          <div className="linea linea-emb" key={i.id}>
            <select value={i.sku} onChange={(e) => cambiar(i.id, "sku", e.target.value)}>
              <option value="">Producto…</option>
              {conStock.map((r) => (
                <option key={r.sku} value={r.sku}>{r.sku} · {r.producto} ({r.disponibles} disp.)</option>
              ))}
            </select>
            <input type="number" min="1" max={disponibles[i.sku] || undefined} value={i.tarimas}
              onChange={(e) => cambiar(i.id, "tarimas", e.target.value)} />
            <button type="button" className="btn-x" title="Quitar" disabled={items.length === 1}
              onClick={() => setItems((is) => is.filter((x) => x.id !== i.id))}>×</button>
          </div>
        ))}
        <button type="button" className="btn-sec" onClick={() => setItems((is) => [...is, nuevoItem()])}>
          + Agregar producto
        </button>
        <p className="nota">Se apartan primero las tarimas más antiguas.</p>
        <button className="btn" disabled={enviando}>{enviando ? "Creando…" : "Crear embarque"}</button>
      </form>

      <div className="panel">
        <div className="panel-cab"><h3>Embarques</h3><BotonExcel nombre="embarques" /></div>
        {!embarques || embarques.length === 0 ? (
          <Vacio texto="Aún no hay embarques." />
        ) : (
          <ul className="lista-emb">
            {embarques.map((e) => (
              <li key={e.id} className={abierto === e.id ? "abierto" : ""}>
                <button className="emb-cab" onClick={() => setAbierto(abierto === e.id ? null : e.id)}>
                  <strong>{e.codigo}</strong>
                  <span>{e.sucursal}</span>
                  <span className="nota">{e.tarimas} tarimas</span>
                  <Estado valor={e.estado} />
                </button>
                {abierto === e.id && <Detalle id={e.id} irARuta={irARuta} />}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
