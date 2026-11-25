import { useDatos } from "./api.js";
import { useApp, fmtFecha, fmtNum, fmtDuracion, Vacio, BotonExcel } from "./util.jsx";

export default function Incidencias() {
  const { version } = useApp();
  const { datos: d, error } = useDatos("/api/incidencias", [version], 5000);
  if (error) return <p className="error">No se pudo cargar el control de incidencias: {error}</p>;
  if (!d) return <p className="cargando">Cargando…</p>;
  const k = d.kpis;
  const maximo = Math.max(1, ...d.por_tipo.map((t) => t.total));

  return (
    <section>
      <div className="panel-cab">
        <h3>Control de recepción</h3>
        <BotonExcel nombre="incidencias" />
      </div>
      <div className="kpis kpis-4">
        <div className="kpi">
          <span className="kpi-etiqueta">Exactitud de descarga</span>
          <span className="kpi-valor">{k.exactitud_pct == null ? "—" : `${k.exactitud_pct}%`}</span>
          <span className="kpi-nota">{fmtNum(k.bultos_aceptados)} bultos aceptados · {fmtNum(k.bultos_rechazados)} rechazados</span>
        </div>
        <div className={`kpi ${k.ocs_parciales ? "kpi-alerta" : ""}`}>
          <span className="kpi-etiqueta">OC con faltantes</span>
          <span className="kpi-valor">{k.ocs_parciales}</span>
          <span className="kpi-nota">Recibidas parcialmente</span>
        </div>
        <div className={`kpi ${k.entregas_con_faltantes ? "kpi-alerta" : ""}`}>
          <span className="kpi-etiqueta">Entregas con faltantes</span>
          <span className="kpi-valor">{k.entregas_con_faltantes}</span>
          <span className="kpi-nota">de {k.entregas_cerradas} recibidas en sucursal</span>
        </div>
        <div className="kpi">
          <span className="kpi-etiqueta">Tiempo promedio</span>
          <span className="kpi-valor kpi-chico">{fmtDuracion(k.descarga_promedio_seg)}</span>
          <span className="kpi-nota">descarga · en sucursal {fmtDuracion(k.sucursal_promedio_seg)}</span>
        </div>
      </div>

      <div className="dos-col">
        <div className="panel">
          <h3>Incidencias por motivo ({k.incidencias_total})</h3>
          {d.por_tipo.length === 0 ? <Vacio texto="Sin incidencias: todo lo escaneado coincidió." /> : (
            <ul className="barras">
              {d.por_tipo.map((t) => (
                <li key={t.tipo}>
                  <span>{t.nombre}</span>
                  <div className="barra-h"><div style={{ width: `${(100 * t.total) / maximo}%` }} /></div>
                  <b>{t.total}</b>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="panel">
          <h3>Pendientes de resolver</h3>
          {d.ocs_parciales.length === 0 && d.entregas_con_faltantes.length === 0 ? (
            <Vacio texto="No hay órdenes ni entregas con faltantes." />
          ) : (
            <ul className="lista-agenda">
              {d.ocs_parciales.map((o) => (
                <li key={`o${o.id}`}>
                  <span className="tipo-punto t-llegada" />
                  <span className="lista-titulo"><b>{o.folio}</b> · {o.proveedor}</span>
                  <span className="atraso">Faltan {o.faltantes} de {o.bultos} bultos</span>
                </li>
              ))}
              {d.entregas_con_faltantes.map((e) => (
                <li key={`e${e.entrega_id}`}>
                  <span className="tipo-punto t-entrega" />
                  <span className="lista-titulo"><b>{e.codigo}</b> · {e.sucursal}</span>
                  <span className="atraso">Llegaron {e.recibidos} de {e.esperados}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="panel">
        <h3>Detalle de incidencias</h3>
        {d.lista.length === 0 ? <Vacio texto="Todavía no hay incidencias." /> : (
          <table>
            <thead><tr><th>Fecha</th><th>Dónde</th><th>Motivo</th><th>Código</th><th>OC / Embarque</th><th>Detalle</th></tr></thead>
            <tbody>
              {d.lista.map((i) => (
                <tr key={i.id}>
                  <td>{fmtFecha(i.fecha)}</td>
                  <td>{i.origen}</td>
                  <td>{i.tipo_nombre}</td>
                  <td><code>{i.codigo}</code></td>
                  <td>{i.oc || i.embarque || "—"}</td>
                  <td className="nota">{i.motivo}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
