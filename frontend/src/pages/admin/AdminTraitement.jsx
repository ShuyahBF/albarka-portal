// AdminTraitement.jsx — Lot 18 : page d'un sous-menu « Traitements » (Fiscal, Comptable, RH).
// Pour l'instant : « Bientôt disponible ». Un collaborateur dont le rôle ne correspond pas voit « Accès réservé »
// (le lien n'apparaît pas dans son menu, mais l'adresse peut être tapée à la main).
import React from "react";
import { useParams, Link } from "react-router-dom";
import { Hourglass, Lock } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { TRAITEMENTS, accesTraitement } from "@/lib/traitements";

export default function AdminTraitement() {
  const { domaine } = useParams();
  const { user } = useAuth();
  const traitement = TRAITEMENTS.find((t) => t.cle === domaine);
  const autorise = traitement && accesTraitement(domaine, user?.roles || []);

  return (
    <div className="p-6 md:p-10" data-testid={`traitement-${domaine}`}>
      <div className="mx-auto max-w-xl rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
        {autorise ? (
          <>
            <Hourglass className="mx-auto mb-3 h-10 w-10 text-[#E5A24B]" />
            <p className="text-xs uppercase tracking-widest text-slate-500">Traitements</p>
            <h1 className="font-display text-2xl text-[#0B1912]">{traitement.label}</h1>
            <p className="mt-4 text-lg font-semibold text-[#0F6B4A]">Bientôt disponible</p>
            <p className="mt-2 text-sm text-slate-600">
              Les traitements {traitement.label === "RH" ? "RH" : traitement.label.toLowerCase() + "s"} du cabinet seront
              proposés ici prochainement.
            </p>
          </>
        ) : (
          <>
            <Lock className="mx-auto mb-3 h-10 w-10 text-slate-400" />
            <h1 className="font-display text-xl text-[#0B1912]">Accès réservé</h1>
            <p className="mt-2 text-sm text-slate-600">Ce traitement ne correspond pas à votre rôle au cabinet.</p>
          </>
        )}
        <Link to="/admin" className="mt-6 inline-block text-sm text-[#0F6B4A] underline">Retour au tableau de bord</Link>
      </div>
    </div>
  );
}
