/*
  Page publique « Demande de service » (lot 53) — sans connexion : depuis la page d'accueil ou le lien
  envoyé par WhatsApp. Le visiteur laisse nom + téléphone, choisit le service et décrit son besoin.
  Adresse : /demande-service (le paramètre ?service=fiscalite pré-sélectionne le service).
*/
import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PublicLayout from "@/components/PublicLayout";
import { API } from "@/lib/api";
import FormulaireDemande from "@/components/demandes/FormulaireDemande";
import axios from "axios";

export default function DemandeService() {
  const [params] = useSearchParams();
  // Numéro WhatsApp du cabinet (si configuré) : alternative à l'écrit pour joindre le cabinet
  const [wa, setWa] = useState({ number: "", message: "" });
  useEffect(() => {
    fetch(`${API}/public/whatsapp-contact`).then((r) => (r.ok ? r.json() : null)).then((d) => d && setWa(d)).catch(() => {});
  }, []);
  const waUrl = wa.number ? `https://wa.me/${wa.number.replace(/[^\d]/g, "")}?text=${encodeURIComponent(wa.message || "")}` : null;
  const initial = ["fiscalite", "rh", "comptable", "autres"].includes(params.get("service")) ? params.get("service") : "";
  return (
    <PublicLayout>
      <section className="py-16 bg-[var(--albarka-paper)]">
        <div className="max-w-2xl mx-auto px-6">
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-3">Demande de service</div>
          <h1 className="font-display text-3xl sm:text-4xl mb-2">Dites-nous ce dont vous avez besoin</h1>
          <p className="text-muted-foreground mb-6">Fiscalité, ressources humaines, comptabilité ou autre : un collaborateur du cabinet vous recontacte rapidement.</p>
          <div className="rounded-xl border bg-white p-5">
            <FormulaireDemande publique serviceInitial={initial}
              onEnvoyer={(fd) => axios.post(`${API}/public/demande-service`, fd)} />
          </div>
          {waUrl && (
            <p className="mt-4 text-sm text-muted-foreground">
              Vous préférez WhatsApp ?{" "}
              <a href={waUrl} target="_blank" rel="noopener noreferrer" className="text-[#0F6B4A] font-medium underline" data-testid="dem-wa">Écrivez-nous directement</a>.
            </p>
          )}
        </div>
      </section>
    </PublicLayout>
  );
}
