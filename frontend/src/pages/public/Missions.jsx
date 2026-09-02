import React from "react";
import PublicLayout from "@/components/PublicLayout";
import { CheckCircle2 } from "lucide-react";

const MISSIONS = [
  {
    title: "Tenue comptable mensuelle",
    detail: "Enregistrement des pièces, rapprochements bancaires, balances et grand livre.",
  },
  {
    title: "Déclarations fiscales",
    detail: "TVA, IS, IRPP, IUTS — dépôt en ligne et suivi des paiements.",
  },
  {
    title: "Paie & CNSS",
    detail: "Édition des bulletins, DAS, cotisations CNSS et retenues IUTS.",
  },
  {
    title: "Bilans et états financiers",
    detail: "Élaboration des états financiers annuels conformes OHADA.",
  },
  {
    title: "Création d'entreprise",
    detail: "Dossiers de constitution, immatriculation RCCM et IFU.",
  },
  {
    title: "Audit et diagnostic",
    detail: "Audit contractuel, diagnostic financier, mise en conformité.",
  },
];

export default function Missions() {
  return (
    <PublicLayout>
      <section className="albarka-hero py-24" data-testid="missions-hero">
        <div className="albarka-hero-grain absolute inset-0 opacity-30 pointer-events-none" />
        <div className="max-w-4xl mx-auto px-6 relative">
          <div className="text-xs uppercase tracking-[0.2em] text-[#E5A24B] mb-3">
            Nos missions
          </div>
          <h1 className="font-display text-4xl md:text-5xl text-white font-semibold">
            Chaque étape de la vie <br />
            <span className="albarka-underline">comptable</span> de votre entreprise.
          </h1>
        </div>
      </section>
      <section className="py-16 bg-[var(--albarka-paper)]">
        <div className="max-w-5xl mx-auto px-6 grid md:grid-cols-2 gap-4">
          {MISSIONS.map((m) => (
            <div
              key={m.title}
              className="albarka-card p-6"
              data-testid={`mission-${m.title.toLowerCase().replace(/\s+/g, '-')}`}
            >
              <div className="flex items-start gap-3">
                <CheckCircle2 className="w-5 h-5 text-[#0F6B4A] flex-shrink-0 mt-0.5" strokeWidth={2.5} />
                <div>
                  <h3 className="font-display text-lg font-semibold mb-1">{m.title}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">{m.detail}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </PublicLayout>
  );
}
