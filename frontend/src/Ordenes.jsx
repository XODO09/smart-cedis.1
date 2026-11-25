import { useState } from "react";
import { api, useDatos } from "./api.js";
import { useApp, Vacio, EnlacePdf, fmtNum, BotonExcel } from "./util.jsx";

let contador = 0;
const nuevaLinea = (sku = "") => ({ id: ++contador, sku, bultos: 10, piezas: 12, peso: 15, volumen: 0.05, solicitadas: "" });
const ESTADOS = { pendiente: "Pendiente", parcial: "Parcial", recibida: "Recibida" };

function Detalle({ id }) {
  const { version } = useApp();
  const { datos: o } = useDatos(`/api/ordenes/${id}`, [version]);
  if (!o) return <p className="cargando">Cargando…</p>;
  return (
    <div className="detalle">
      <div className="acciones-fila">
        <EnlacePdf href={`/api/ordenes/${id}/etiquetas.pdf`}>Etiquetas de bultos (PDF)</EnlacePdf>
        <span className="nota">Una por caja, con QR de bulto, OC, proveedor, destino, SKU y piezas. El proveedor las pega.</span>
      </div>
      <table>
        <thead><tr><th>Producto</th><th>Solicitadas</th><th>Facturadas</th><th>Bultos</th><th>Peso</th><th>Volumen</th></tr></thead>
        <tbody>
          {o.lineas.map((l) => (
            <tr key={l.sku}>
              <td><b>{l.sku}</b><div className="nota">{l.producto}</div></td>
              <td>{fmtNum(l.solicitadas)}</td><td>{fmtNum(l.facturadas)}</td>
              <td>{l.bultos}</td><td>{fmtNum(l.peso_kg)} kg</td><td>{l.volumen_m3.toFixed(2)} m³</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="nota">Total: {o.bultos} bultos · {fmtNum(o.peso_kg)} kg · {o.volumen_m3} m³ · destino {o.sucursal}</p>
    </div>
  );
}

export default function Ordenes() {
  const { version, refrescar, avisar } = useApp();
  const { datos: productos } = useDatos("/api/productos");
  const { datos: proveedores } = useDatos("/api/proveedores");
  const { datos: sucursales } = useDatos("/api/sucursales");
  const { datos: ordenes } = useDatos("/api/ordenes", [version]);
  const [folio, setFolio] = useState("");
  const [factura, setFactura] = useState("");
  const [proveedorId, setProveedorId] = useState("");
  const [sucursalId, setSucursalId] = useState("");
  const [lineas, setLineas] = useState([nuevaLinea()]);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState(null);
  const [abierta, setAbierta] = useState(null);

  const cambiar = (id, campo, valor) => setLineas((ls) => ls.map((l) => (l.id === id ? { ...l, [campo]: valor } : l)));
  const tot = lineas.reduce((t, l) => ({
    bultos: t.bultos + (Number(l.bultos) || 0),
    piezas: t.piezas + (Number(l.bultos) || 0) * (Number(l.piezas) || 0),
    peso: t.peso + (Number(l.bultos) || 0) * (Number(l.peso) || 0),
    volumen: t.volumen + (Number(l.bultos) || 0) * (Number(l.volumen) || 0),
  }), { bultos: 0, piezas: 0, peso: 0, volumen: 0 });

  const ejemplo = () => {
    if (!productos || !proveedores || !sucursales) return;
    const n = (ordenes || []).length + 1;
    setFolio(`OC-2026-${String(200 + n)}`);
    setFactura(`FAC-X-${50000 + n * 37}`);
    setProveedorId(String(proveedores[0].id));
    setSucursalId(String(sucursales[3].id));
    setLineas([{ ...nuevaLinea(productos[0].sku), bultos: 12, piezas: 12, peso: 14.5, volumen: 0.045 },
      { ...nuevaLinea(productos[3].sku), bultos: 8, piezas: 10, peso: 21, volumen: 0.06 }]);
    setError(null);
  };

  const enviar = async (e) => {
    e.preventDefault();
    setError(null);
    setEnviando(true);
    try {
      const o = await api.post("/api/ordenes", {
        folio, folio_factura: factura, proveedor_id: Number(proveedorId) || 0, sucursal_id: Number(sucursalId) || 0,
        lineas: lineas.map((l) => ({
          sku: l.sku, bultos: Number(l.bultos), piezas_por_bulto: Number(l.piezas), peso_kg: Number(l.peso),
          volumen_m3: Number(l.volumen), piezas_solicitadas: l.solicitadas === "" ? null : Number(l.solicitadas) })),
      });
      avisar(`OC ${o.folio} creada con ${o.bultos} bultos. Ya puedes imprimir sus etiquetas.`, "ok");
      setFolio(""); setFactura(""); setLineas([nuevaLinea()]);
      setAbierta(o.id);
      refrescar();
    } catch (err) { setError(err.message); }
    setEnviando(false);
  };

  return (
    <section className="dos-col dos-col-form">
      <form className="panel" onSubmit={enviar}>
        <div className="panel-cab">
          <h3>Nueva orden de compra</h3>
          <button type="button" className="btn-sec" onClick={ejemplo}>Cargar ejemplo</button>
        </div>
        <div className="campos campos-2">
          <label>Folio de la OC<input value={folio} onChange={(e) => setFolio(e.target.value)} placeholder="OC-2026-0150" /></label>
          <label>Folio de la factura<input value={factura} onChange={(e) => setFactura(e.target.value)} placeholder="FAC-A-12345" /></label>
          <label>Proveedor
            <select value={proveedorId} onChange={(e) => setProveedorId(e.target.value)}>
              <option value="">Elige…</option>
              {(proveedores || []).map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
            </select>
          </label>
          <label>Sucursal destino
            <select value={sucursalId} onChange={(e) => setSucursalId(e.target.value)}>
              <option value="">Elige…</option>
              {(sucursales || []).map((s) => <option key={s.id} value={s.id}>{s.nombre}</option>)}
            </select>
          </label>
        </div>
        <p className="nota">El folio de factura es único: no puede repetirse en otra OC.</p>

        <h4>Factura desglosada por bulto</h4>
        <div className="lineas">
          <div className="linea linea-oc linea-cab">
            <span>Producto</span><span>Bultos</span><span>Pzas / bulto</span><span>Kg / bulto</span><span>m³ / bulto</span><span>Solicitadas</span><span />
          </div>
          {lineas.map((l) => (
            <div className="linea linea-oc" key={l.id}>
              <select value={l.sku} onChange={(e) => cambiar(l.id, "sku", e.target.value)}>
                <option value="">Producto…</option>
                {(productos || []).map((p) => <option key={p.sku} value={p.sku}>{p.sku} · {p.nombre}</option>)}
              </select>
              <input type="number" min="1" value={l.bultos} onChange={(e) => cambiar(l.id, "bultos", e.target.value)} />
              <input type="number" min="1" value={l.piezas} onChange={(e) => cambiar(l.id, "piezas", e.target.value)} />
              <input type="number" min="0" step="any" value={l.peso} onChange={(e) => cambiar(l.id, "peso", e.target.value)} />
              <input type="number" min="0" step="any" value={l.volumen} onChange={(e) => cambiar(l.id, "volumen", e.target.value)} />
              <input type="number" min="1" value={l.solicitadas} placeholder="= facturadas" onChange={(e) => cambiar(l.id, "solicitadas", e.target.value)} />
              <button type="button" className="btn-x" title="Quitar" disabled={lineas.length === 1}
                onClick={() => setLineas((ls) => ls.filter((x) => x.id !== l.id))}>×</button>
            </div>
          ))}
        </div>
        <button type="button" className="btn-sec" onClick={() => setLineas((ls) => [...ls, nuevaLinea()])}>+ Agregar producto</button>
        <p className="nota">Un bulto lleva un solo producto. «Solicitadas» son las piezas de la OC; si lo dejas vacío se toma lo facturado.</p>
        <p><b>{tot.bultos}</b> bultos · {fmtNum(tot.piezas)} piezas · {fmtNum(Math.round(tot.peso))} kg · {tot.volumen.toFixed(2)} m³</p>
        {error && <p className="error form-error">{error}</p>}
        <button className="btn" disabled={enviando}>{enviando ? "Guardando…" : "Crear OC y generar bultos"}</button>
      </form>

      <div className="panel">
        <div className="panel-cab"><h3>Órdenes de compra</h3><BotonExcel nombre="ordenes" /></div>
        {!ordenes || ordenes.length === 0 ? <Vacio texto="Aún no hay órdenes de compra." /> : (
          <ul className="lista-emb">
            {ordenes.map((o) => (
              <li key={o.id} className={abierta === o.id ? "abierto" : ""}>
                <button className="emb-cab" onClick={() => setAbierta(abierta === o.id ? null : o.id)}>
                  <strong>{o.folio}</strong>
                  <span>{o.proveedor}<div className="nota">Factura {o.folio_factura} → {o.sucursal}</div></span>
                  <span className="nota">{o.recibidos}/{o.bultos} bultos{o.cita_inicio ? ` · cita ${o.cita_inicio.slice(5, 10)} ${o.cita_inicio.slice(11, 16)}` : " · sin cita"}</span>
                  <span className={`badge oc-${o.estado}`}>{ESTADOS[o.estado]}</span>
                </button>
                {abierta === o.id && <Detalle id={o.id} />}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
