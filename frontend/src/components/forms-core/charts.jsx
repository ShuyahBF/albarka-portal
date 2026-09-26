/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  charts.jsx : petites briques visuelles partagées par les statistiques
  (FormStats) et la vue d'ensemble de la bibliothèque (FormsLibrary) :
    - PALETTE : couleurs vives utilisées pour les graphiques ;
    - AnimatedNumber : chiffre qui « compte » de 0 jusqu'à sa valeur ;
    - KpiCard : carte d'indicateur colorée (dégradé, icône, chiffre animé) ;
    - ChartCard : carte blanche avec titre, icône et sous-titre, qui apparaît
      en glissant légèrement vers le haut (animation CSS) ;
    - Meter : barre horizontale animée (entonnoir, classements) ;
    - ChartTip : infobulle arrondie des graphiques Recharts.
*/
import React, { useEffect, useRef, useState } from "react";
import { cx } from "./ui";

// Couleurs des graphiques (la couleur du site est ajoutée en tête par l'écran)
export const PALETTE = ["#6366F1", "#10B981", "#F59E0B", "#EF4444", "#0EA5E9", "#8B5CF6", "#EC4899", "#14B8A6", "#F97316", "#84CC16"];

// Thèmes des cartes d'indicateurs : dégradé de fond, couleur de l'icône et du chiffre
export const KPI_THEMES = {
  indigo: { bg: "from-indigo-50 to-white", ring: "ring-indigo-100", icon: "bg-indigo-500", text: "text-indigo-700" },
  emerald: { bg: "from-emerald-50 to-white", ring: "ring-emerald-100", icon: "bg-emerald-500", text: "text-emerald-700" },
  amber: { bg: "from-amber-50 to-white", ring: "ring-amber-100", icon: "bg-amber-500", text: "text-amber-700" },
  sky: { bg: "from-sky-50 to-white", ring: "ring-sky-100", icon: "bg-sky-500", text: "text-sky-700" },
  rose: { bg: "from-rose-50 to-white", ring: "ring-rose-100", icon: "bg-rose-500", text: "text-rose-700" },
  violet: { bg: "from-violet-50 to-white", ring: "ring-violet-100", icon: "bg-violet-500", text: "text-violet-700" },
};

// Animation d'apparition (définie une seule fois pour toute la page)
export function ChartStyles() {
  return (
    <style>{`
      @keyframes fcFadeUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
      .fc-fade-up { animation: fcFadeUp .5s ease-out both; }
      @media (prefers-reduced-motion: reduce) { .fc-fade-up { animation: none; } }
    `}</style>
  );
}

// Chiffre animé : passe de 0 à `value` en ~0,9 s (courbe douce), garde les décimales
export function AnimatedNumber({ value, decimals = 0, suffix = "" }) {
  const [shown, setShown] = useState(0);
  const frame = useRef(0);
  useEffect(() => {
    const target = Number(value) || 0;
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / 900);
      const eased = 1 - Math.pow(1 - t, 3);          // décélération en fin d'animation
      setShown(target * eased);
      if (t < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [value]);
  return <>{shown.toLocaleString("fr-FR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}{suffix}</>;
}

// Carte d'indicateur colorée. `value` numérique = animé ; texte = affiché tel quel.
export function KpiCard({ label, value, hint, icon: Icon, theme = "indigo", decimals = 0, suffix = "", delay = 0, testId }) {
  const th = KPI_THEMES[theme] || KPI_THEMES.indigo;
  return (
    <div className={cx("fc-fade-up rounded-xl ring-1 bg-gradient-to-br p-4 shadow-sm hover:shadow-md hover:-translate-y-0.5 transition", th.bg, th.ring)}
      style={{ animationDelay: `${delay}ms` }} data-testid={testId}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</p>
        {Icon && <span className={cx("inline-flex h-8 w-8 items-center justify-center rounded-lg text-white shadow-sm", th.icon)}><Icon className="h-4 w-4" /></span>}
      </div>
      <p className={cx("text-3xl font-display font-bold tabular-nums leading-tight", th.text)}>
        {typeof value === "number" ? <AnimatedNumber value={value} decimals={decimals} suffix={suffix} /> : value}
      </p>
      {hint && <p className="text-[11px] text-slate-500 mt-0.5">{hint}</p>}
    </div>
  );
}

// Carte de graphique : titre avec pastille d'icône colorée, sous-titre, contenu
export function ChartCard({ title, subtitle, icon: Icon, color = "#6366F1", right, children, className, delay = 0, testId }) {
  return (
    <div className={cx("fc-fade-up rounded-xl border border-slate-200 bg-white p-5 shadow-sm", className)} style={{ animationDelay: `${delay}ms` }} data-testid={testId}>
      <div className="flex items-start justify-between gap-2 mb-3">
        <div>
          <h3 className="text-sm font-display font-bold text-slate-900 flex items-center gap-2">
            {Icon && <span className="inline-flex h-6 w-6 items-center justify-center rounded-md" style={{ background: `${color}1A`, color }}><Icon className="h-3.5 w-3.5" /></span>}
            {title}
          </h3>
          {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
        </div>
        {right}
      </div>
      {children}
    </div>
  );
}

// Barre horizontale animée : la largeur grandit de 0 à `pct` % à l'affichage
export function Meter({ label, value, pct, color, sub }) {
  const [w, setW] = useState(0);
  useEffect(() => { const t = setTimeout(() => setW(Math.max(0, Math.min(100, pct || 0))), 60); return () => clearTimeout(t); }, [pct]);
  return (
    <div className="text-xs">
      <div className="flex justify-between gap-2 mb-1">
        <span className="text-slate-700 truncate font-medium">{label}</span>
        <span className="tabular-nums text-slate-500">{value}{sub ? <span className="text-slate-400"> · {sub}</span> : null}</span>
      </div>
      <div className="h-2.5 rounded-full bg-slate-100 overflow-hidden">
        <div className="h-full rounded-full transition-[width] duration-1000 ease-out" style={{ width: `${w}%`, background: color }} />
      </div>
    </div>
  );
}

// Infobulle des graphiques : fond blanc arrondi, pastille de couleur par série
export function ChartTip({ active, payload, label, labelFormatter, unit = "réponse(s)" }) {
  if (!active || !payload || !payload.length) return null;
  return (
    <div className="rounded-lg bg-white/95 ring-1 ring-slate-200 shadow-lg px-3 py-2 text-xs">
      {label !== undefined && <p className="font-semibold text-slate-800 mb-1">{labelFormatter ? labelFormatter(label) : label}</p>}
      {payload.map((p, i) => (
        <p key={i} className="flex items-center gap-1.5 text-slate-600">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color || p.payload?.fill }} />
          {p.name && p.name !== "count" ? `${p.name} : ` : ""}<strong className="tabular-nums text-slate-900">{p.value}</strong> {unit}
        </p>
      ))}
    </div>
  );
}
