/*
  Lot 98 — TABLEAU DES PAIEMENTS des services web, avec le REÇU À IMPRIMER bien visible (règles 15 et 16 : un pictogramme sur chaque action, des couleurs sobres sur l'important).
  Une ligne par paiement : date et heure, service, RÉFÉRENCE (bleu), montant (vert), origine, puis la colonne « Reçu » : gros bouton BLEU avec une imprimante.
  Pour le support : « dans la colonne Reçu, cliquez sur le bouton bleu en forme d'imprimante ».
  Utilisé par le super-admin (Paramètres → Services Web, avec Annuler) et par le DG / les rôles de consultation (Mes Services Web, lecture seule).
*/
import React, { useMemo, useState } from "react";
import { toast } from "sonner";
import { Printer, Undo2, ChevronsDown, Smartphone, Pencil, Receipt } from "lucide-react";
import { extractError } from "@/lib/api";
import { imprimerRecu } from "@/lib/recuServiceWeb";

const PAGE = 15;
const fmtMontant = (m, dev) => `${Number(m || 0).toLocaleString("fr-FR")} ${dev || "FCFA"}`;

export default function TableauPaiementsServices({ services, cheminRecu, surAnnuler, titre = "Paiements enregistrés et reçus" }) {
  const [nb, setNb] = useState(PAGE);
  const lignes = useMemo(() => services.flatMap((s) => (s.paiements || []).map((p) => ({ s, p })))
    .sort((a, b) => String(b.p.paye_le).localeCompare(String(a.p.paye_le))), [services]);

  return (
    <div className="albarka-card overflow-x-auto border-t-4 border-sky-500" data-testid="tableau-paiements-services">
      <div className="flex flex-wrap items-center justify-between gap-2 bg-sky-50 px-4 py-3">
        <h2 className="inline-flex items-center gap-2 text-base font-semibold text-sky-900"><Receipt className="h-5 w-5" /> {titre}</h2>
        <span className="text-xs text-sky-800">Pour imprimer un reçu : cliquez sur le bouton bleu <Printer className="inline h-3.5 w-3.5" /> de la colonne « Reçu ».</span>
      </div>
      <table className="w-full text-sm tableau">
        <thead>
          <tr className="text-left border-b bg-slate-50 text-slate-700">
            <th className="p-3">Date et heure</th><th className="p-3">Service</th>
            <th className="p-3 text-sky-800">Référence du paiement</th>
            <th className="p-3 text-right text-emerald-800">Montant</th><th className="p-3">Origine</th>
            <th className="p-3 text-center text-sky-800">Reçu</th>{surAnnuler && <th className="p-3 text-right">Correction</th>}
          </tr>
        </thead>
        <tbody>
          {lignes.slice(0, nb).map(({ s, p }) => (
            <tr key={p.id} className="border-b last:border-0" data-testid={`ligne-paiement-${p.id}`}>
              <td className="p-3 whitespace-nowrap text-slate-700">{new Date(p.paye_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
              <td className="p-3 font-medium text-[#0F3D2E] whitespace-pre-line">{s.service}</td>
              <td className="p-3 font-mono text-xs font-semibold text-sky-700 break-all">{p.reference || "—"}</td>
              <td className="p-3 text-right font-semibold tabular-nums text-emerald-700">{fmtMontant(p.montant, s.devise)}</td>
              <td className="p-3">{p.source === "sms"
                ? <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800"><Smartphone className="h-3 w-3" /> SMS reçu</span>
                : <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700"><Pencil className="h-3 w-3" /> Saisi à la main</span>}</td>
              <td className="p-3 text-center">
                <button type="button" onClick={() => imprimerRecu(cheminRecu(s, p)).catch((e) => toast.error(extractError(e)))}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-sky-700 focus:outline-none focus:ring-2 focus:ring-sky-300"
                  title="Imprimer le reçu de ce paiement" aria-label={`Imprimer le reçu du paiement ${p.reference || ""}`} data-testid={`recu-${p.id}`}>
                  <Printer className="h-4 w-4" /> Imprimer le reçu
                </button>
              </td>
              {surAnnuler && (
                <td className="p-3 text-right">
                  <button type="button" onClick={() => surAnnuler(s, p)} className="inline-flex items-center gap-1 rounded-lg border border-red-200 px-2.5 py-1 text-xs text-red-700 hover:bg-red-50" title="Annuler ce paiement" aria-label="Annuler ce paiement">
                    <Undo2 className="h-3.5 w-3.5" /> Annuler
                  </button>
                </td>
              )}
            </tr>
          ))}
          {lignes.length === 0 && <tr><td colSpan={surAnnuler ? 7 : 6} className="p-4 text-center text-muted-foreground">Aucun paiement enregistré pour le moment.</td></tr>}
        </tbody>
      </table>
      {lignes.length > nb && (
        <div className="p-3">
          <button type="button" onClick={() => setNb(nb + PAGE)} className="inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-sky-300 bg-sky-50 px-3 py-2 text-sm text-sky-800 hover:bg-sky-100">
            <ChevronsDown className="h-4 w-4" /> Afficher plus ({lignes.length - nb} paiements restants)
          </button>
        </div>
      )}
    </div>
  );
}
