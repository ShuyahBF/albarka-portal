// Petites fonctions d'affichage partagées par les écrans OCR du cabinet.

// Montant en FCFA, avec 2 décimales sous 100 FCFA (le coût d'une pièce est
// souvent de quelques FCFA : l'arrondir à l'entier ferait perdre l'info).
export function formatXof(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  const digits = Math.abs(n) < 100 ? 2 : 0;
  return `${n.toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits })} FCFA`;
}

// Ratio 0-1 affiché en pourcentage entier ("—" si pas encore mesuré).
export function formatPercent(ratio) {
  if (ratio === null || ratio === undefined) return "—";
  return `${Math.round(Number(ratio) * 100)} %`;
}

// Durée en secondes avec une décimale.
export function formatDuration(ms) {
  if (!ms) return "—";
  return `${(Number(ms) / 1000).toFixed(1)} s`;
}

// Nom court d'un modèle pour les tableaux ("claude-sonnet-5" → "Sonnet 5",
// "claude-haiku-4-5-20251001" → "Haiku 4.5" : la date de version est masquée).
export function shortModel(modelId) {
  if (!modelId) return "—";
  return modelId
    .replace(/^claude-/, "")
    .replace(/-\d{8}$/, "")
    .split("-")
    .map((part, i) => (i === 0 ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(" ")
    .replace(/(\d) (\d)/, "$1.$2");
}

// Valeur d'un champ extrait affichée lisiblement (listes/objets en JSON
// indenté au lieu de "[object Object]").
export function displayValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}
