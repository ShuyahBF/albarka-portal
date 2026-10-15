import React from "react";
import { Link } from "react-router-dom";
import PublicLayout from "@/components/PublicLayout";

// Adresse de contact des pages juridiques (celle déclarée à Meta pour l'application ALBARKA)
export const CONTACT_JURIDIQUE = "jfrancois_ouoba@yahoo.fr";

// Mise en page commune des pages juridiques publiques (confidentialité, conditions de service).
// `sections` : [{ titre, avant: [paragraphes], puces: [lignes], apres: [paragraphes] }]
export default function PageJuridique({ kicker, titre, titreAccent, dateMaj, sections, testId }) {
  return (
    <PublicLayout>
      <section className="py-16 bg-[var(--albarka-paper)]">
        <div className="max-w-3xl mx-auto px-6" data-testid={testId}>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-3">{kicker}</div>
          <h1 className="font-display text-4xl md:text-5xl text-foreground mb-3">
            {titre} <span className="albarka-underline">{titreAccent}</span>
          </h1>
          <p className="text-sm text-muted-foreground mb-3">
            ALBARKA Consulting BF · albarka-bf.com · Dernière mise à jour : {dateMaj}
          </p>
          {/* Liens croisés entre les pages juridiques */}
          <p className="text-sm mb-10">
            <Link to="/confidentialite" className="text-[#0F6B4A] underline underline-offset-2">Politique de confidentialité</Link>
            {" · "}
            <Link to="/conditions" className="text-[#0F6B4A] underline underline-offset-2">Conditions de service</Link>
            {" · "}
            <Link to="/suppression-donnees" className="text-[#0F6B4A] underline underline-offset-2">Suppression des données</Link>
          </p>

          <div className="space-y-8">
            {sections.map((s) => (
              <div key={s.titre} className="albarka-card p-6 space-y-3">
                <h2 className="text-lg font-semibold text-[#0F6B4A]">{s.titre}</h2>
                {(s.avant || []).map((p) => (
                  <p key={p} className="text-sm leading-relaxed text-foreground/90">{p}</p>
                ))}
                {s.puces && (
                  <ul className="list-disc pl-5 space-y-1.5 text-sm leading-relaxed text-foreground/90">
                    {s.puces.map((p) => <li key={p}>{p}</li>)}
                  </ul>
                )}
                {(s.apres || []).map((p) => (
                  <p key={p} className="text-sm leading-relaxed text-foreground/90">{p}</p>
                ))}
              </div>
            ))}
          </div>
        </div>
      </section>
    </PublicLayout>
  );
}
