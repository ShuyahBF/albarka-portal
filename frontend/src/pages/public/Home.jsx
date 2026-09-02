import React from "react";
import { Link } from "react-router-dom";
import {
  ShieldCheck,
  Sparkles,
  Calculator,
  Landmark,
  FileSpreadsheet,
  Users,
  ArrowRight,
  CheckCircle2,
} from "lucide-react";
import { Button } from "@/components/ui/button";

const SPECIALITES = [
  {
    icon: Calculator,
    title: "Tenue comptable",
    text: "Saisie, rapprochements bancaires, états financiers mensuels et annuels selon les normes OHADA.",
  },
  {
    icon: Landmark,
    title: "Fiscalité",
    text: "Déclarations TVA, IS, IRPP, IUTS, accompagnement en cas de contrôle et optimisation fiscale.",
  },
  {
    icon: Users,
    title: "Paie & RH",
    text: "Bulletins, déclarations CNSS/IUTS, contrats de travail et suivi social de vos équipes.",
  },
  {
    icon: FileSpreadsheet,
    title: "Conseil & audit",
    text: "Diagnostic, création d'entreprise, mise en conformité et audit contractuel.",
  },
];

const CHIFFRES = [
  { value: "12+", label: "Années d'expérience" },
  { value: "150", label: "Clients actifs" },
  { value: "24h", label: "Délai de réponse" },
  { value: "100%", label: "Confidentialité" },
];

export default function Home() {
  return (
    <div>
      {/* HERO */}
      <section className="albarka-hero relative overflow-hidden" data-testid="hero-section">
        <div className="albarka-hero-grain absolute inset-0 opacity-40 pointer-events-none" />
        <div className="max-w-7xl mx-auto px-6 py-20 md:py-28 relative">
          <div className="grid md:grid-cols-12 gap-10 items-center">
            <div className="md:col-span-7">
              <div className="inline-flex items-center gap-2 rounded-full bg-white/10 border border-white/20 px-3 py-1 text-xs text-white/80 mb-6">
                <Sparkles className="w-3.5 h-3.5 text-[#E5A24B]" />
                Cabinet certifié — Ouagadougou, Burkina Faso
              </div>
              <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl leading-[1.05] text-white font-semibold tracking-tight">
                Votre <span className="albarka-underline">comptabilité</span>,
                <br />
                votre <span className="text-[#E5A24B]">tranquillité.</span>
              </h1>
              <p className="mt-6 text-white/70 max-w-xl text-lg leading-relaxed">
                Cabinet ALBARKA accompagne les entreprises et entrepreneurs burkinabè
                dans la tenue comptable, la fiscalité, la paie et l'audit — dans un
                portail sécurisé, avec une IA qui analyse vos pièces au dépôt.
              </p>
              <div className="mt-8 flex flex-col sm:flex-row gap-3">
                <Link to="/login">
                  <Button
                    className="bg-[#E5A24B] text-[#0B1912] hover:bg-[#F3B968] h-12 px-6 text-base font-medium"
                    data-testid="hero-cta-portal"
                  >
                    Accéder à mon espace
                    <ArrowRight className="w-4 h-4 ml-2" />
                  </Button>
                </Link>
                <Link to="/contact">
                  <Button
                    variant="outline"
                    className="border-white/20 bg-transparent text-white hover:bg-white/10 hover:text-white h-12 px-6 text-base"
                    data-testid="hero-cta-contact"
                  >
                    Nous contacter
                  </Button>
                </Link>
              </div>
              <div className="mt-10 flex flex-wrap gap-x-6 gap-y-3 text-sm text-white/60">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-[#0F6B4A]" strokeWidth={2.5} />
                  Analyse IA des pièces
                </div>
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-[#0F6B4A]" strokeWidth={2.5} />
                  OTP sécurisé
                </div>
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-[#0F6B4A]" strokeWidth={2.5} />
                  Conforme OHADA
                </div>
              </div>
            </div>

            {/* Right-side stat card */}
            <div className="md:col-span-5">
              <div className="grid grid-cols-2 gap-3">
                {CHIFFRES.map((c, i) => (
                  <div
                    key={c.label}
                    className={`rounded-2xl p-6 border ${
                      i % 3 === 0
                        ? "bg-[#0F6B4A]/30 border-[#0F6B4A]/60"
                        : "bg-white/5 border-white/10"
                    }`}
                    data-testid={`stat-${c.label.replace(/\s+/g, '-').toLowerCase()}`}
                  >
                    <div className="font-display text-4xl text-white font-semibold">
                      {c.value}
                    </div>
                    <div className="text-xs text-white/60 mt-1 uppercase tracking-wider">
                      {c.label}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-3 rounded-2xl bg-white/5 border border-white/10 p-6">
                <div className="flex items-start gap-3">
                  <ShieldCheck className="w-5 h-5 text-[#E5A24B] flex-shrink-0 mt-0.5" />
                  <div>
                    <div className="text-white text-sm font-medium mb-1">
                      Vos données restent chez vous
                    </div>
                    <div className="text-white/60 text-xs leading-relaxed">
                      Portail chiffré, accès par OTP, séparation stricte des espaces
                      client par tenant.
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* SPECIALITES */}
      <section className="py-24 bg-[var(--albarka-paper)]" data-testid="specialites-section">
        <div className="max-w-7xl mx-auto px-6">
          <div className="max-w-2xl mb-14">
            <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-3">
              Nos domaines
            </div>
            <h2 className="font-display text-3xl md:text-4xl text-foreground mb-4">
              Une expertise complète, sous <em>un seul toit</em>.
            </h2>
            <p className="text-muted-foreground text-lg leading-relaxed">
              De la saisie comptable au conseil stratégique, ALBARKA couvre tous les
              domaines de gestion financière et fiscale de votre entreprise.
            </p>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
            {SPECIALITES.map((s) => (
              <div
                key={s.title}
                className="albarka-card p-6"
                data-testid={`specialite-${s.title.toLowerCase().replace(/\s+/g, '-')}`}
              >
                <div className="w-11 h-11 rounded-lg bg-[#0F6B4A]/10 text-[#0F6B4A] flex items-center justify-center mb-4">
                  <s.icon className="w-5 h-5" />
                </div>
                <h3 className="font-display text-lg font-semibold text-foreground mb-2">
                  {s.title}
                </h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{s.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA finale */}
      <section className="py-20 bg-[#0B1912]" data-testid="final-cta-section">
        <div className="max-w-4xl mx-auto px-6 text-center">
          <h2 className="font-display text-3xl md:text-4xl text-white mb-4">
            Prêt à confier votre <span className="text-[#E5A24B]">comptabilité</span> ?
          </h2>
          <p className="text-white/70 mb-8 max-w-xl mx-auto">
            Rejoignez les entreprises qui gèrent leurs pièces, échéances et missions
            dans un portail unique, avec l'accompagnement d'un cabinet dédié.
          </p>
          <Link to="/login">
            <Button
              className="bg-[#E5A24B] text-[#0B1912] hover:bg-[#F3B968] h-12 px-8 text-base font-medium"
              data-testid="final-cta-portal"
            >
              Ouvrir mon espace client
              <ArrowRight className="w-4 h-4 ml-2" />
            </Button>
          </Link>
        </div>
      </section>
    </div>
  );
}
