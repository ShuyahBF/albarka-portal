import React from "react";
import { Link } from "react-router-dom";

// Liens vers les pages juridiques publiques (exigés par Meta et utiles aux utilisateurs) :
// affichés sur l'accueil public et la page de connexion, en plus du pied de page du site.
// `sombre` : texte clair pour un fond sombre.
export default function LiensJuridiques({ sombre = false, testId = "liens-juridiques" }) {
  const classe = sombre
    ? "text-white/60 hover:text-[#E5A24B]"
    : "text-muted-foreground hover:text-[#0F6B4A]";
  return (
    <nav className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs" aria-label="Informations légales" data-testid={testId}>
      <Link to="/confidentialite" className={`underline underline-offset-2 ${classe}`}>Politique de confidentialité</Link>
      <Link to="/conditions" className={`underline underline-offset-2 ${classe}`}>Conditions de service</Link>
      <Link to="/suppression-donnees" className={`underline underline-offset-2 ${classe}`}>Suppression des données</Link>
    </nav>
  );
}
