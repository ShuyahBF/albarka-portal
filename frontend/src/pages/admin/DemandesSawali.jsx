/*
  Lot 92 — Page « Demandes à SAWALI » de la barre latérale (DG, Direction, Secrétariat : mêmes droits).
  Remplace la rubrique des Paramètres du lot 91 ; le contenu est le panneau DemandesSawaliPanel.
*/
import React from "react";
import { Send } from "lucide-react";
import DemandesSawaliPanel from "@/pages/admin/DemandesSawaliPanel";

export default function DemandesSawali() {
  return (
    <div className="space-y-4" data-testid="page-demandes-sawali">
      <h1 className="text-2xl font-semibold flex items-center gap-2"><Send className="w-6 h-6 text-[#0F6B4A]" /> Demandes à SAWALI</h1>
      <DemandesSawaliPanel />
    </div>
  );
}
