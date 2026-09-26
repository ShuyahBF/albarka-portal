/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  ui.js : boîte à outils de styles (classes Tailwind) partagée par les écrans,
  reprise du design des Formulaires de SAWALI :
    - boutons pleins colorés et compacts (Remplir, Éditer, Données, Stats…) ;
    - champs compacts avec étiquette en petites majuscules ;
    - pastilles filtrantes arrondies, onglets soulignés ;
    - cartes blanches arrondies, fenêtres (modales) avec en-tête à icône.
  La couleur principale est celle du site (jeton Tailwind « primary »).
  Utilisation : import { ui, cx } from "@/components/forms-core/ui";
*/

// Assemble des classes en ignorant les valeurs vides (cx("a", cond && "b"))
export const cx = (...parts) => parts.filter(Boolean).join(" ");

export const ui = {
  // ---- En-tête de page : petite ligne au-dessus du titre, titre, sous-titre
  eyebrow: "text-xs uppercase tracking-[0.3em] text-slate-500",
  h1: "text-2xl font-display font-bold flex items-center gap-2 text-slate-900",
  h1Icon: "h-5 w-5 text-primary",
  subtitle: "text-sm text-slate-500 mt-1 max-w-3xl",

  // ---- Boutons principaux (taille normale)
  btnPrimary: "inline-flex items-center justify-center gap-2 rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition",
  btnSecondary: "inline-flex items-center justify-center gap-2 rounded-lg ring-1 ring-slate-300 bg-white text-slate-700 px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50 transition",
  btnGhost: "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50",
  btnDanger: "inline-flex items-center justify-center gap-2 rounded-lg bg-rose-500 text-white px-4 py-2 text-sm font-medium hover:bg-rose-600 disabled:opacity-50 transition",
  // Lien discret « outil » (ex. « Analytics global », « Gérer »)
  btnSoft: "inline-flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 text-primary px-3 py-1.5 text-xs hover:bg-primary hover:text-primary-foreground transition",
  btnTool: "inline-flex items-center gap-1 rounded ring-1 ring-slate-300 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50",

  // ---- Petits boutons d'action pleins colorés (cartes, lignes de tableau)
  act: {
    primary: "inline-flex items-center gap-1 text-[11px] rounded bg-primary text-primary-foreground px-2.5 py-1.5 hover:opacity-90 disabled:opacity-50",
    dark: "inline-flex items-center gap-1 text-[11px] rounded bg-slate-900 text-white px-2.5 py-1.5 hover:bg-slate-800 disabled:opacity-50",
    sky: "inline-flex items-center gap-1 text-[11px] rounded bg-sky-600 text-white px-2.5 py-1.5 hover:bg-sky-700 disabled:opacity-50",
    indigo: "inline-flex items-center gap-1 text-[11px] rounded bg-indigo-600 text-white px-2.5 py-1.5 hover:bg-indigo-700 disabled:opacity-50",
    emerald: "inline-flex items-center gap-1 text-[11px] rounded bg-emerald-600 text-white px-2.5 py-1.5 hover:bg-emerald-700 disabled:opacity-50",
    amber: "inline-flex items-center gap-1 text-[11px] rounded bg-amber-500 text-white px-2.5 py-1.5 hover:bg-amber-600 disabled:opacity-50",
    slate: "inline-flex items-center gap-1 text-[11px] rounded bg-slate-500 text-white px-2.5 py-1.5 hover:bg-slate-600 disabled:opacity-50",
    danger: "inline-flex items-center gap-1 text-[11px] rounded bg-rose-500 text-white px-2.5 py-1.5 hover:bg-rose-600 disabled:opacity-50",
    // Bouton icône seul, plein et coloré (actions d'une ligne de liste)
    iconDark: "inline-flex items-center justify-center h-7 w-7 rounded bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50",
    iconAmber: "inline-flex items-center justify-center h-7 w-7 rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50",
    iconEmerald: "inline-flex items-center justify-center h-7 w-7 rounded bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50",
    iconSky: "inline-flex items-center justify-center h-7 w-7 rounded bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50",
    iconIndigo: "inline-flex items-center justify-center h-7 w-7 rounded bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50",
    iconDanger: "inline-flex items-center justify-center h-7 w-7 rounded bg-rose-500 text-white hover:bg-rose-600 disabled:opacity-50",
    // Bouton icône seul, discret (ligne de tableau)
    icon: "inline-flex items-center justify-center h-7 w-7 rounded ring-1 ring-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:text-slate-900 disabled:opacity-40",
  },

  // ---- Champs de saisie
  label: "block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1",
  input: "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:bg-slate-50 disabled:text-slate-500",
  inputError: "w-full rounded-lg border border-rose-400 ring-2 ring-rose-200 bg-white px-3 py-2 text-sm focus:outline-none",
  inputSm: "w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm focus:outline-none focus:border-primary",
  select: "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15",
  textarea: "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15",
  // Variantes « en ligne » (largeur du contenu, pour les barres de filtres)
  selectInline: "w-auto rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15",
  inputInline: "w-auto rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/15",
  help: "mt-1 text-[11px] text-slate-400",
  error: "mt-1 text-xs text-rose-600 flex items-center gap-1",
  // Case à cocher / bouton radio aux couleurs du site
  check: "h-4 w-4 rounded border-slate-300 accent-[hsl(var(--primary))] cursor-pointer",
  checkLabel: "inline-flex items-center gap-2 text-sm text-slate-700 cursor-pointer select-none",
  // Recherche avec loupe (placer l'icône avec searchIcon)
  searchWrap: "relative w-full md:w-72",
  searchIcon: "absolute left-2 top-2 h-3.5 w-3.5 text-slate-400",
  searchInput: "w-full pl-7 pr-2 py-1.5 text-xs rounded ring-1 ring-slate-300 bg-white focus:outline-none focus:ring-primary",

  // ---- Pastilles filtrantes (catégories) et onglets soulignés
  chip: (active) => cx("text-xs px-3 py-1.5 rounded-full ring-1 transition inline-flex items-center gap-1",
    active ? "bg-primary text-primary-foreground ring-primary" : "bg-white text-slate-700 ring-slate-200 hover:ring-primary/50"),
  tabs: "flex gap-2 border-b border-slate-200 overflow-x-auto",
  tab: (active) => cx("px-3 py-2 text-sm border-b-2 transition whitespace-nowrap inline-flex items-center gap-1.5",
    active ? "border-primary text-primary font-semibold" : "border-transparent text-slate-500 hover:text-slate-900"),

  // ---- Conteneurs
  card: "rounded-xl border border-slate-200 bg-white p-4",
  panel: "rounded-xl border border-slate-200 bg-white p-5 space-y-3",
  panelTitle: "font-display font-bold text-slate-900 flex items-center gap-2",
  panelIcon: "h-4 w-4 text-primary",
  stat: "rounded-xl border border-slate-200 bg-white px-4 py-3",
  statLabel: "text-[10px] uppercase tracking-wider text-slate-500 font-semibold",
  statValue: "text-2xl font-display font-bold tabular-nums text-slate-900",
  code: "text-[10px] font-mono bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded",
  empty: "text-center text-slate-400 py-10 italic text-sm",
  loading: "text-center text-slate-500 py-10 text-sm",

  // ---- Badges d'état
  badge: {
    green: "text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700",
    grey: "text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 text-slate-600",
    sky: "text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-sky-50 text-sky-700 font-semibold tabular-nums",
    amber: "text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 text-amber-800",
    red: "text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-100 text-rose-700",
    violet: "text-[10px] inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-violet-100 text-violet-700",
  },

  // ---- Tableaux
  table: "w-full text-sm",
  thead: "bg-slate-50 text-left text-[10px] uppercase tracking-wider text-slate-500",
  th: "px-3 py-2 font-semibold",
  tr: "border-t border-slate-100 hover:bg-slate-50/60",
  td: "px-3 py-2 align-middle",

  // ---- Fenêtres (modales)
  overlay: "fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center p-4",
  modal: "bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 space-y-4 max-h-[92vh] overflow-y-auto",
  modalLg: "bg-white rounded-2xl shadow-2xl w-full max-w-2xl p-6 space-y-4 max-h-[92vh] overflow-y-auto",
  modalTitle: "font-display font-bold text-lg flex items-center gap-2 text-slate-900",
  modalIcon: "h-5 w-5 text-primary",
  modalText: "text-xs text-slate-600",
  modalFooter: "flex items-center justify-end gap-2 pt-1",
  close: "text-slate-400 hover:text-slate-700",
};
