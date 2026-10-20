// Lot 52 — thèmes des synthèses mensuelles (mêmes clés que côté serveur : albarka_client_space.THEMES)
export const THEMES = [
  { key: "rh", label: "Rapport RH", emoji: "👥" },
  { key: "cnss", label: "CNSS", emoji: "🛡️" },
  { key: "fiscal", label: "Fiscal", emoji: "🧾" },
  { key: "comptable", label: "Comptable", emoji: "📒" },
];
export const libelleMois = (periode) => {
  const d = new Date(`${periode}-01T12:00:00`);
  return Number.isNaN(d.getTime()) ? periode : d.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
};
