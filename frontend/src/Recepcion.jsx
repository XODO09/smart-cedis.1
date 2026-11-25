import { useEffect, useState } from "react";
import { api, useDatos } from "./api.js";
import { useApp, fmtFecha, Vacio, EnlacePdf } from "./util.jsx";
import Descargas from "./Descarga.jsx";

let contador = 0;
const nuevaLinea = (sku = "") => ({ id: ++contador, sku, tarimas: 1, cantidad: 48, peso: 600 });

export default function Recepcion({ cita = null, soltarCita = () => {} }) {
  const { version, refrescar, avisar } = useApp();
  const { datos: productos } = useDatos("/api/productos");
  const { datos: proveedores } = useDatos("/api/proveedores");
  const { datos: camiones } = useDatos("/api/camiones", [version]);
  const { datos: recepciones } = useDatos("/api/recepciones", [version]);

  const [placas, setPlacas] = useState("");
  const [proveedorId, setProveedorId] = useState("");
  const [tipo, setTipo] = useState("Abarrotes");
  const [tipoCamion, setTipoCamion] = useState("Torton");
  const [capacidad, setCapacidad] = useState(14);
  const [lineas, setLineas] = useState([nuevaLinea()]);
  const [auto, setAuto] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [resultado, setResultado] = useState(null);

  // Si llegamos desde la agenda, se precargan los datos de la cita
  useEffect(() => {
    if (!cita) return;
    if (cita.placas) setPlacas(cita.placas);
    if (cita.proveedor_id) setProveedorId(String(cita.proveedor_id));
    if (cita.tipo_mercancia) setTipo(cita.tipo_mercancia);
    setResultado(null);
  }, [cita]);

  const placasNorm = placas.trim().toUpperCase();
  const camionNuevo = placasNorm && camiones && !camiones.some((c) => c.placas === placasNorm);
  const totalTarimas = lineas.reduce((s, l) => s + (Number(l.tarimas) || 0), 0);

  const cambiar = (id, campo, valor) =>
    setLineas((ls) => ls.map((l) => (l.id === id ? { ...l, [campo]: valor } : l)));

  const cargarEjemplo = () => {
    if (!productos || !proveedores) return;
    setPlacas("TRX-401-A");
    setProveedorId(String(proveedores[0].id));
    setTipo("Abarrotes");
    setTipoCamion("Tráiler 53'");
    setCapacidad(26);
    setLineas([
      { ...nuevaLinea(productos[0].sku), tarimas: 4, cantidad: 48, peso: 640 },
      { ...nuevaLinea(productos[1].sku), tarimas: 3, cantidad: 60, peso: 700 },
      { ...nuevaLinea(productos[4].sku), tarimas: 2, cantidad: 120, peso: 850 },
    ]);
    setResultado(null);
  };

  const enviar = async (e) => {
    e.preventDefault();
    if (!placasNorm) return avisar("Escribe las placas del camión.", "error");
    if (!proveedorId) return avisar("Elige un proveedor.", "error");
    if (lineas.some((l) => !l.sku)) return avisar("Elige el producto en todas las líneas.", "error");
    setEnviando(true);
    try {
      const tarimas = lineas.flatMap((l) =>
        Array.from({ length: Number(l.tarimas) }, () => ({
          sku: l.sku, cantidad: Number(l.cantidad), peso_kg: Number(l.peso),
        })));
      const r = await api.post("/api/recepciones", {
        placas: placasNorm,
        proveedor_id: Number(proveedorId),
        tipo_mercancia: tipo,
        tarimas,
        tipo_camion: tipoCamion,
        capacidad_camion: Number(capacidad),
        ubicar_automaticamente: auto,
        cita_id: cita ? cita.id : null,
      });
      const inv = await api.get("/api/inventario");
      const ubic = Object.fromEntries(inv.tarimas.map((t) => [t.codigo, t.ubicacion]));
      setResultado({ ...r, detalle: r.tarimas.map((c) => ({ codigo: c, ubicacion: ubic[c] })) });
      avisar(`Recepción #${r.recepcion_id} registrada: ${r.tarimas.length} tarimas.`, "ok");
      setLineas([nuevaLinea()]);
      setPlacas("");
      soltarCita();
      refrescar();
    } catch (err) {
      avisar(err.message, "error");
    } finally {
      setEnviando(false);
    }
  };

  const ubicarPendientes = async (id) => {
    try {
      const r = await api.post(`/api/recepciones/${id}/ubicar`);
      avisar(`${r.ubicadas.length} tarimas ubicadas${r.sin_ubicar.length ? `, ${r.sin_ubicar.length} sin lugar` : ""}.`,
        r.sin_ubicar.length ? "error" : "ok");
      refrescar();
    } catch (err) {
      avisar(err.message, "error");
    }
  };

  const manual = !!cita && !cita.oc_id;
  return (
    <>
    <Descargas cita={cita} />
    <details className="manual" open={manual}>
      <summary>Recepción manual sin orden de compra (solo pruebas)</summary>
    <section className="dos-col dos-col-form">
      <form className="panel" onSubmit={enviar}>
        <div className="panel-cab">
          <h3>Llegada de camión</h3>
          <button type="button" className="btn-sec" onClick={cargarEjemplo}>Cargar ejemplo</button>
        </div>

        {cita && (
          <div className="aviso cita-aviso">
            Esta recepción cumple la cita #{cita.id}: {cita.titulo} ({cita.inicio.slice(11, 16)}
            {cita.tarimas_esperadas ? `, se esperaban ${cita.tarimas_esperadas} tarimas` : ""}).
            <button type="button" className="btn-sec" onClick={soltarCita}>Quitar</button>
          </div>
        )}
        <div className="campos">
          <label>Placas del camión
            <input list="lista-camiones" value={placas} onChange={(e) => setPlacas(e.target.value)}
              placeholder="VER-101-A" />
            <datalist id="lista-camiones">
              {(camiones || []).map((c) => <option key={c.id} value={c.placas}>{c.tipo}</option>)}
            </datalist>
          </label>
          <label>Proveedor
            <select value={proveedorId} onChange={(e) => setProveedorId(e.target.value)}>
              <option value="">Elige…</option>
              {(proveedores || []).map((p) => <option key={p.id} value={p.id}>{p.nombre}</option>)}
            </select>
          </label>
          <label>Tipo de mercancía
            <input value={tipo} onChange={(e) => setTipo(e.target.value)} />
          </label>
        </div>

        {camionNuevo && (
          <div className="aviso">
            Camión nuevo: se registrará con estos datos.
            <div className="campos campos-2">
              <label>Tipo<input value={tipoCamion} onChange={(e) => setTipoCamion(e.target.value)} /></label>
              <label>Capacidad (tarimas)
                <input type="number" min="1" value={capacidad} onChange={(e) => setCapacidad(e.target.value)} />
              </label>
            </div>
          </div>
        )}

        <h4>Tarimas recibidas</h4>
        <div className="lineas">
          <div className="linea linea-cab">
            <span>Producto</span><span>Tarimas</span><span>Unidades c/u</span><span>Peso c/u (kg)</span><span />
          </div>
          {lineas.map((l) => (
            <div className="linea" key={l.id}>
              <select value={l.sku} onChange={(e) => cambiar(l.id, "sku", e.target.value)}>
                <option value="">Producto…</option>
                {(productos || []).map((p) => <option key={p.sku} value={p.sku}>{p.sku} · {p.nombre}</option>)}
              </select>
              <input type="number" min="1" value={l.tarimas} onChange={(e) => cambiar(l.id, "tarimas", e.target.value)} />
              <input type="number" min="1" value={l.cantidad} onChange={(e) => cambiar(l.id, "cantidad", e.target.value)} />
              <input type="number" min="1" value={l.peso} onChange={(e) => cambiar(l.id, "peso", e.target.value)} />
              <button type="button" className="btn-x" title="Quitar línea" disabled={lineas.length === 1}
                onClick={() => setLineas((ls) => ls.filter((x) => x.id !== l.id))}>×</button>
            </div>
          ))}
        </div>
        <button type="button" className="btn-sec" onClick={() => setLineas((ls) => [...ls, nuevaLinea()])}>
          + Agregar producto
        </button>

        <label className="check">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          Asignar ubicación automáticamente al recibir
        </label>

        <button className="btn" disabled={enviando}>
          {enviando ? "Registrando…" : `Registrar recepción (${totalTarimas} ${totalTarimas === 1 ? "tarima" : "tarimas"})`}
        </button>

        {resultado && (
          <div className="resultado">
            <strong>Recepción #{resultado.recepcion_id} · camión {resultado.placas}</strong>
            <div className="nota">
              {resultado.ubicadas} de {resultado.tarimas.length} tarimas ubicadas
              {resultado.sin_ubicar.length > 0 && ` · ${resultado.sin_ubicar.length} por ubicar`}
            </div>
            <div className="chips">
              {resultado.detalle.map((t) => (
                <span key={t.codigo} className={`chip ${t.ubicacion ? "" : "chip-alerta"}`}>
                  {t.codigo} → {t.ubicacion || "por ubicar"}
                </span>
              ))}
            </div>
            <div className="acciones-fila">
              <EnlacePdf href={`/api/recepciones/${resultado.recepcion_id}/etiquetas.pdf`}>
                Imprimir etiquetas con QR (PDF)
              </EnlacePdf>
              <span className="nota">Una etiqueta de 4×6" por tarima, lista para pegar.</span>
            </div>
          </div>
        )}
      </form>

      <div className="panel">
        <h3>Recepciones registradas</h3>
        {!recepciones || recepciones.length === 0 ? (
          <Vacio texto="Aún no hay recepciones." />
        ) : (
          <table>
            <thead><tr><th>#</th><th>Llegada</th><th>Camión</th><th>Proveedor</th><th>Tarimas</th><th /></tr></thead>
            <tbody>
              {recepciones.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{fmtFecha(r.fecha_llegada)}</td>
                  <td>{r.placas}</td>
                  <td>{r.proveedor}<div className="nota">{r.tipo_mercancia}</div></td>
                  <td>{r.tarimas}</td>
                  <td>
                    <div className="acciones-fila">
                      {r.por_ubicar > 0 && (
                        <button className="btn-sec" onClick={() => ubicarPendientes(r.id)}>
                          Ubicar {r.por_ubicar}
                        </button>
                      )}
                      <EnlacePdf href={`/api/recepciones/${r.id}/etiquetas.pdf`}>Etiquetas</EnlacePdf>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
    </details>
    </>
  );
}
