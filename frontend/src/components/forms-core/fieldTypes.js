/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE : corriger dans
  ShuyahBF/Claude/forms-core puis resynchroniser avec forms-core/sync.sh).

  Catalogue des types de champs côté écran (miroir de forms_core/fields.py),
  création d'un champ neuf, visibilité conditionnelle et petits utilitaires.
*/
import {
  Type, AlignLeft, Mail, Phone, Hash, Calendar, CalendarClock, ChevronDownSquare,
  CircleDot, CheckSquare, ListChecks, ToggleLeft, Star, Gauge, Link2, Table, Paperclip,
  PenLine, Heading,
} from "lucide-react";

// type → libellé, icône, porte une valeur ?
export const FIELD_TYPES = [
  { type: "text", label: "Texte court", icon: Type },
  { type: "textarea", label: "Paragraphe", icon: AlignLeft },
  { type: "email", label: "E-mail", icon: Mail },
  { type: "tel", label: "Téléphone", icon: Phone },
  { type: "number", label: "Nombre", icon: Hash },
  { type: "date", label: "Date", icon: Calendar },
  { type: "datetime", label: "Date et heure", icon: CalendarClock },
  { type: "select", label: "Liste déroulante", icon: ChevronDownSquare },
  { type: "radio", label: "Choix unique", icon: CircleDot },
  { type: "checkbox", label: "Cases à cocher", icon: CheckSquare },
  { type: "multiselect", label: "Choix multiples (liste)", icon: ListChecks },
  { type: "boolean", label: "Oui / Non", icon: ToggleLeft },
  { type: "rating", label: "Note (étoiles)", icon: Star },
  { type: "scale", label: "Échelle 0-10", icon: Gauge },
  { type: "url", label: "Lien (URL)", icon: Link2 },
  { type: "table", label: "Tableau", icon: Table },
  { type: "file", label: "Fichier joint", icon: Paperclip },
  { type: "signature", label: "Signature", icon: PenLine },
  { type: "section", label: "Titre / texte", icon: Heading, noValue: true },
];

export const TYPE_BY_KEY = Object.fromEntries(FIELD_TYPES.map((t) => [t.type, t]));
export const CHOICE_TYPES = ["select", "radio", "checkbox", "multiselect"];

// Identifiant court et stable (clé des réponses).
export const newId = (prefix = "f") => `${prefix}_${Math.random().toString(16).slice(2, 10)}`;

// Champ neuf, prêt à être configuré dans le constructeur.
export function newField(type) {
  const base = { id: newId(), type, label: TYPE_BY_KEY[type]?.label || "Question", help: "", required: false, width: "full", placeholder: "", show_if: null };
  if (CHOICE_TYPES.includes(type)) base.options = ["Option 1", "Option 2"];
  if (type === "rating") base.max = 5;
  if (type === "table") base.columns = [{ key: "c1", label: "Désignation", type: "text" }, { key: "c2", label: "Quantité", type: "number" }];
  if (type === "file") base.accept = "";
  if (type === "section") base.label = "Nouvelle section";
  return base;
}

export const newPage = (n = 1) => ({ id: newId("p"), title: `Page ${n}`, fields: [] });

// Même règle que le serveur (validation.is_visible).
export function isVisible(field, answers) {
  const cond = field.show_if;
  if (!cond || !cond.field) return true;
  const target = answers?.[cond.field];
  const expected = cond.equals;
  if (Array.isArray(target)) return target.includes(expected);
  if (typeof target === "boolean") return String(expected).toLowerCase() === (target ? "oui" : "non") || String(expected) === String(target);
  return target !== undefined && target !== null && String(target) === String(expected);
}

export const isEmpty = (v) => v === undefined || v === null || v === "" || (Array.isArray(v) && v.length === 0);

// Valeur lisible d'une réponse (tableaux, fichiers, oui/non…).
export function readableValue(field, value) {
  if (isEmpty(value)) return "—";
  if (field.type === "boolean") return value === true ? "Oui" : value === false ? "Non" : String(value);
  if (field.type === "table" && Array.isArray(value)) return `${value.length} ligne(s)`;
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return field.type === "signature" ? "Signé" : value.filename || value.file_id || "Fichier";
  return String(value);
}

// Message d'erreur d'une réponse d'API (texte, {message, errors} ou tableau Pydantic).
export function errorText(err, fallback = "Une erreur est survenue") {
  const d = err?.response?.data?.detail;
  if (!d) return fallback;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg).filter(Boolean).join(" · ") || fallback;
  return d.message || fallback;
}

export const formatDateTime = (iso) => {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }); } catch { return iso; }
};

// Téléchargement d'un fichier protégé (CSV, QR) : la requête passe par apiClient (jeton).
export async function downloadBlob(apiClient, url, filename) {
  const r = await apiClient.get(url, { responseType: "blob" });
  const href = URL.createObjectURL(r.data);
  const a = document.createElement("a");
  a.href = href; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 2000);
}
