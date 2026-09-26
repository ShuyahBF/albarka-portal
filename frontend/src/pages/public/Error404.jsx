/*
  Page « ERREUR 404 » neutre — affichée à un collaborateur qui tente de se
  connecter hors de la liste blanche (appareil / réseau non autorisé), sans
  révéler que ses identifiants étaient bons (albarka_access.py).
*/
import React from "react";
import { Link } from "react-router-dom";

export default function Error404() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-white px-4" data-testid="error-404-page">
      <div className="text-center">
        <div className="font-mono text-7xl font-bold text-slate-800">404</div>
        <div className="mt-2 text-lg font-semibold tracking-widest text-slate-600">ERREUR</div>
        <p className="mt-3 text-sm text-slate-500">La page demandée est introuvable.</p>
        <Link to="/" className="inline-block mt-6 text-sm text-[#0F6B4A] underline">Retour à l'accueil</Link>
      </div>
    </div>
  );
}
