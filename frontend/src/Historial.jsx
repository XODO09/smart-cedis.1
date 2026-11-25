import { useDatos } from "./api.js";
import { useApp, fmtFecha, Vacio, BotonExcel } from "./util.jsx";

const TIPOS = {
  recepcion: "Recepción",
  almacenamiento: "Almacenamiento",
  asignacion_embarque: "Asignación a embarque",
  despacho: "Despacho",
};

export default function Historial() {
  const { version } = useApp();
  const { datos, error } = useDatos("/api/movimientos?limite=100", [version], 5000);
  if (error) return <p className="error">No se pudo cargar el historial: {error}</p>;
  if (!datos) return <p className="cargando">Cargando…</p>;
  return (
    <section className="panel">
      <div className="panel-cab"><h3>Historial de movimientos</h3><BotonExcel nombre="movimientos" /></div>
      {datos.length === 0 ? (
        <Vacio texto="Todavía no hay movimientos." />
      ) : (
        <table>
          <thead><tr><th>Fecha</th><th>Tarima</th><th>Movimiento</th><th>Origen</th><th>Destino</th><th>Operador</th></tr></thead>
          <tbody>
            {datos.map((m) => (
              <tr key={m.id}>
                <td>{fmtFecha(m.fecha)}</td>
                <td><code>{m.tarima}</code></td>
                <td>{TIPOS[m.tipo] || m.tipo}</td>
                <td>{m.origen}</td>
                <td>{m.destino}</td>
                <td>{m.operador}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
