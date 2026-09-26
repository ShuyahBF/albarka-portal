/*
  « Vérifier un document » (lot 7) — page publique ouverte en scannant le QR
  code imprimé sur une facture, une facture proforma, un document généré
  (avis / ordre de mission…) ou un tableau de paie. Elle confirme que le
  document a bien été émis par le cabinet (numéro, date, client, montant).
  API : GET /public/verify/{token} (sans compte).
*/
import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ShieldCheck, ShieldAlert, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";

// Montant « 59 474 FCFA »
const money = (v, cur) => `${Number(v || 0).toLocaleString("fr-FR", { maximumFractionDigits: 0 })} ${cur === "XOF" || !cur ? "FCFA" : cur}`;
const STATUS = { paid: "Réglée", partial: "Réglée en partie", unpaid: "À régler", proforma: "Proforma (non payable)" };

export default function VerifyDocument() {
  const { token } = useParams();
  const [state, setState] = useState({ loading: true });

  useEffect(() => {
    apiClient.get(`/public/verify/${encodeURIComponent(token)}`)
      .then(({ data }) => setState({ data }))
      .catch(() => setState({ error: true }));
  }, [token]);

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4 py-10" data-testid="verify-page">
      <div className="w-full max-w-md rounded-2xl bg-white shadow-xl ring-1 ring-slate-200 overflow-hidden">
        {state.loading && <p className="p-10 text-center text-slate-500"><Loader2 className="h-5 w-5 animate-spin inline mr-2" /> Vérification…</p>}
        {state.error && (
          <div className="p-8 text-center" data-testid="verify-invalid">
            <ShieldAlert className="mx-auto h-14 w-14 text-rose-500" />
            <h1 className="mt-3 text-xl font-bold text-slate-900">Document inconnu</h1>
            <p className="mt-2 text-sm text-slate-500">Ce code ne correspond à aucun document émis par le cabinet. Méfiez-vous de ce document et contactez le cabinet.</p>
          </div>
        )}
        {state.data && (
          <div data-testid="verify-valid">
            {/* Bandeau vert : document authentique */}
            <div className="bg-emerald-600 px-6 py-5 text-white text-center">
              <ShieldCheck className="mx-auto h-12 w-12" />
              <h1 className="mt-2 text-lg font-bold">Document authentique</h1>
              <p className="text-sm text-emerald-50">Émis par {state.data.issuer}</p>
            </div>
            <dl className="divide-y divide-slate-100 px-6 py-2 text-sm">
              {[["Type", state.data.kind], ["Numéro", state.data.number], ["Date", state.data.date ? new Date(state.data.date).toLocaleDateString("fr-FR") : "—"],
                ["Client", state.data.client], ["Objet", state.data.title],
                ...(state.data.amount !== undefined ? [["Montant", money(state.data.amount, state.data.currency)]] : []),
                ...(state.data.status && STATUS[state.data.status] ? [["Situation", STATUS[state.data.status]]] : []),
              ].filter(([, v]) => v).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 py-2.5"><dt className="text-slate-500">{k}</dt><dd className="font-semibold text-slate-900 text-right">{v}</dd></div>
              ))}
            </dl>
          </div>
        )}
        <div className="border-t border-slate-100 px-6 py-3 text-center">
          <Link to="/" className="text-xs text-[#0F6B4A] underline">Portail du cabinet</Link>
        </div>
      </div>
    </div>
  );
}
