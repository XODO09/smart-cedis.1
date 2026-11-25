import { Component } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

/** Si algo falla al dibujar una pantalla, se muestra un aviso con salida en vez de dejar la página en blanco. */
class Contenedor extends Component {
  constructor(props) { super(props); this.state = { fallo: null }; }
  static getDerivedStateFromError(fallo) { return { fallo }; }
  render() {
    if (!this.state.fallo) return this.props.children;
    return (
      <div className="panel" style={{ maxWidth: 520, margin: "80px auto" }}>
        <h3>Algo salió mal en esta pantalla</h3>
        <p className="nota">{String(this.state.fallo.message || this.state.fallo)}</p>
        <button className="btn" onClick={() => location.reload()}>Recargar</button>
      </div>
    );
  }
}

createRoot(document.getElementById("root")).render(<Contenedor><App /></Contenedor>);
