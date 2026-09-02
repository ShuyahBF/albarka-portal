import React from "react";
import ReactDOM from "react-dom/client";
import "@/index.css";
// Pilote ALBARKA : point d'entrée minimal (login + espace client + vue
// cabinet). L'App.js hérité de Sawali reste dans le dépôt comme référence
// pour les prochaines phases mais n'est plus le point de montage par défaut.
import PilotApp from "@/pilot/PilotApp";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <PilotApp />
  </React.StrictMode>,
);
