import React, { useState } from "react";
import { CreditCard, X } from "lucide-react";
import PaymentLinkForm from "@/components/PaymentLinkForm";

/**
 * PaymentBubble — bulle flottante d'accès rapide au module Paiements,
 * même principe que ChatBubble.jsx mais pour générer un lien de paiement
 * PawaPay sans quitter la page courante. Réservée au rôle "caissier" (voir
 * PortalLayout.jsx, qui décide seul de la monter ou non).
 *
 * Empilée au-dessus de la bulle Chat interne (bottom-24 au lieu de bottom-6,
 * même côté droit) — jamais à gauche : la sidebar y est ancrée en
 * permanence (menu, badges de rôles, bouton Déconnexion), une bulle
 * flottante à cet endroit les recouvrirait immanquablement.
 */
export default function PaymentBubble() {
  const [open, setOpen] = useState(false);

  return (
    <>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-24 right-6 z-50 h-14 w-14 rounded-full bg-[#E5A24B] text-white shadow-lg hover:bg-[#C77F1F] transition-all hover:scale-105 flex items-center justify-center"
          data-testid="payment-bubble-toggle"
          title="Générer un lien de paiement"
        >
          <CreditCard className="w-6 h-6" />
        </button>
      )}

      {open && (
        <div
          className="fixed z-50 bg-white shadow-2xl border border-border flex flex-col bottom-24 right-6 w-[min(360px,calc(100vw-3rem))] max-h-[70vh] rounded-xl overflow-hidden"
          data-testid="payment-bubble-panel"
        >
          <div className="p-3 border-b border-border flex items-center justify-between bg-[#E5A24B] text-white rounded-t-xl">
            <div className="flex items-center gap-2">
              <CreditCard className="w-4 h-4" />
              <span className="text-sm font-medium">Lien de paiement</span>
            </div>
            <button onClick={() => setOpen(false)} className="hover:bg-white/10 p-1 rounded" data-testid="payment-bubble-close">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="p-3 overflow-y-auto">
            <PaymentLinkForm compact />
          </div>
        </div>
      )}
    </>
  );
}
