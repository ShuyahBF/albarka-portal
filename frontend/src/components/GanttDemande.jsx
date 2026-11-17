/*
  Lot 117 — Cellule « Disponibilité estimée » du tableau des demandes à SAWALI : barre de Gantt (de la demande à la date estimée) sur un axe commun,
  avec la ligne « aujourd'hui ». Couleur + texte + pictogramme (jamais la couleur seule) : bleu = prévue, vert = réalisée, rouge = date dépassée,
  gris hachuré = pas encore de date, gris = refusée.
*/
import React from "react";
import { CalendarClock, CheckCircle2, AlertTriangle, Ban, HelpCircle } from "lucide-react";
import { barreGantt, positionAujourdhui } from "@/lib/ganttDemandes";

const STYLE = {
  prevue: { fond: "bg-blue-500", texte: "text-blue-800", Picto: CalendarClock },
  realisee: { fond: "bg-green-600", texte: "text-green-800", Picto: CheckCircle2 },
  en_retard: { fond: "bg-red-600", texte: "text-red-700", Picto: AlertTriangle },
  sans_date: { fond: "bg-gray-300", texte: "text-gray-600", Picto: HelpCircle, hachure: true },
  refusee: { fond: "bg-gray-400", texte: "text-gray-600", Picto: Ban },
  a_remonter: { fond: "", texte: "text-gray-500", Picto: HelpCircle },
};

export default function GanttDemande({ demande, bornes, maintenant = Date.now() }) {
  const b = barreGantt(demande, bornes, maintenant);
  const s = STYLE[b.etat];
  const Picto = s.Picto;
  return (
    <div className="min-w-[200px] w-[220px]" data-testid={`gantt-${demande.id}`} data-etat={b.etat}>
      <div className="relative h-4 rounded bg-slate-100" role="img" aria-label={b.libelle}>
        {b.largeur > 0 && (
          <div className={`absolute top-0.5 bottom-0.5 rounded ${s.fond}`} title={b.libelle}
            style={{ left: `${b.gauche}%`, width: `${b.largeur}%`, ...(s.hachure ? { backgroundImage: "repeating-linear-gradient(45deg, rgba(255,255,255,.7) 0 4px, transparent 4px 8px)" } : {}) }} />
        )}
        {/* ligne « aujourd'hui » */}
        <div className="absolute top-0 bottom-0 w-px bg-orange-500" style={{ left: `${positionAujourdhui(bornes, maintenant)}%` }} title="Aujourd'hui" />
      </div>
      <div className={`mt-1 flex items-start gap-1 text-xs ${s.texte}`}><Picto className="w-3.5 h-3.5 shrink-0 mt-px" aria-hidden="true" /><span>{b.libelle}</span></div>
    </div>
  );
}
