// Affichage UNIQUE d'un client dans toutes les listes et sélecteurs (demande du 14/11/2026) :
//   STRUCTURE en gras et bleu, suivie de « - » et du RESPONSABLE (propriétaire) :   « Pharmacie WEND DENDA - SANNA Azize ».
// Structure = raison sociale (`company`) ; responsable = nom du compte (`full_name`). Sans raison sociale : le nom seul, en gras et bleu.
// `libelleClient` donne le même texte en clair pour les endroits qui n'acceptent pas de mise en forme (info-bulle, texte brut).
import React from "react";

export const libelleClient = (c) => {
  if (!c) return "";
  const structure = (c.company || "").trim();
  const responsable = (c.full_name || "").trim();
  return structure ? (responsable ? `${structure} - ${responsable}` : structure) : responsable;
};

export default function NomClient({ client, className = "" }) {
  if (!client) return null;
  const structure = (client.company || "").trim();
  const responsable = (client.full_name || "").trim();
  const principal = structure || responsable;
  return (
    <span className={className} data-testid="nom-client">
      <b className="font-bold text-[#0B4F8A]">{principal}</b>
      {structure && responsable ? <span className="text-slate-700"> - {responsable}</span> : null}
    </span>
  );
}
