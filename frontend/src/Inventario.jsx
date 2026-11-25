import { useState } from "react";
import { useDatos } from "./api.js";
import { useApp, Estado, Vacio, QR, fmtNum, colorSku, BotonExcel } from "./util.jsx";

export default function Inventario() {
  const { version } = useApp();
  const [sku, setSku] = useState("");
  const [estado, setEstado] = useState("");
  const [buscar, setBuscar] = useState("");

  const { datos: productos } = useDatos("/api/productos");
  const params = new URLSearchParams();
  if (sku) params.set("sku", sku);
  if (estado) params.set("estado", estado);
  const { datos, error } = useDatos(`/api/inventario?${params}`, [version], 5000);

  if (error) return <p className="error">No se pudo cargar el inventario: {error}</p>;
  if (!datos) return <p className="cargando">Cargando…</p>;

  const q = buscar.trim().toLowerCase();
  const filas = datos.tarimas.filter((t) =>
    !q || t.codigo.toLowerCase().includes(q) || (t.ubicacion || "").toLowerCase().includes(q));

  return (
    <section>
      <div className="panel">
        <h3>Existencias por producto</h3>
        {datos.resumen.length === 0 ? (
          <Vacio texto="No hay tarimas almacenadas." />
        ) : (
          <table>
            <thead>
              <tr><th>SKU</th><th>Producto</th><th>Tarimas</th><th>Unidades</th><th>Disponibles</th><th>En embarque</th></tr>
            </thead>
            <tbody>
              {datos.resumen.map((r) => (
                <tr key={r.sku}>
                  <td><span className="punto" style={{ background: colorSku(r.sku) }} /> {r.sku}</td>
                  <td>{r.producto}</td>
                  <td>{r.tarimas}</td>
                  <td>{fmtNum(r.unidades)}</td>
                  <td>{r.disponibles}</td>
                  <td>{r.comprometidas}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <div className="panel-cab">
          <h3>Tarimas ({filas.length})</h3>
          <BotonExcel nombre="inventario" />
          <div className="filtros">
            <input placeholder="Buscar tarima o ubicación" value={buscar} onChange={(e) => setBuscar(e.target.value)} />
            <select value={sku} onChange={(e) => setSku(e.target.value)}>
              <option value="">Todos los productos</option>
              {(productos || []).map((p) => <option key={p.sku} value={p.sku}>{p.sku} · {p.nombre}</option>)}
            </select>
            <select value={estado} onChange={(e) => setEstado(e.target.value)}>
              <option value="">En el CEDIS</option>
              <option value="recibida">Por ubicar</option>
              <option value="almacenada">Almacenadas</option>
              <option value="asignada">En embarque</option>
              <option value="despachada">Despachadas</option>
            </select>
          </div>
        </div>
        {filas.length === 0 ? (
          <Vacio texto="No hay tarimas con ese filtro." />
        ) : (
          <table>
            <thead>
              <tr><th>Tarima</th><th>Producto</th><th>Unidades</th><th>Peso</th><th>Ubicación</th><th>Estado</th><th>QR</th></tr>
            </thead>
            <tbody>
              {filas.map((t) => (
                <tr key={t.codigo}>
                  <td><code>{t.codigo}</code></td>
                  <td><span className="punto" style={{ background: colorSku(t.sku) }} /> {t.sku} · {t.producto}</td>
                  <td>{fmtNum(t.cantidad)}</td>
                  <td>{fmtNum(t.peso_kg)} kg</td>
                  <td>{t.ubicacion || "—"}</td>
                  <td><Estado valor={t.estado} /></td>
                  <td>
                    <a href={`/api/tarimas/${t.codigo}/etiqueta.pdf`} target="_blank" rel="noreferrer"
                      title={`Abrir la etiqueta de ${t.codigo} para imprimir`}>
                      <QR codigo={t.codigo} tam={38} />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
