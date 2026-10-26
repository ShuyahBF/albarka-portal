/*
  Lot 72 — Liste de documents du cabinet pour l'espace client (Rapports, Ordres de mission, domaines).
  Chaque ligne : titre, catégorie · référence · date, pastille « Nouveau », boutons Ouvrir et Télécharger.
*/
import React from "react";
import { Download, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ouvrirDocument } from "@/lib/ouvrirDocument";

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "");

export default function ListeDocumentsClient({ items, apres, vide = "Aucun document pour l'instant.", testid = "docs-client" }) {
  if (!items.length) return <div className="albarka-card p-6 text-center text-muted-foreground text-sm" data-testid={`${testid}-vide`}>{vide}</div>;
  return (
    <div className="space-y-2" data-testid={testid}>
      {items.map((it) => (
        <div key={`${it.source}-${it.id}`} className="albarka-card p-4 flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[220px]">
            <div className="font-medium flex items-center gap-2">
              {it.title}
              {it.is_new && <span className="albarka-chip text-[10px] bg-[#E5A24B]/20 text-[#8a5a14]">Nouveau</span>}
            </div>
            <div className="text-xs text-muted-foreground">{it.category_label}{it.reference ? ` · ${it.reference}` : ""}{it.date ? ` · ${fmtDate(it.date)}` : ""}</div>
          </div>
          <Button size="sm" variant="outline" onClick={() => ouvrirDocument(it, false, apres)}><Eye className="w-4 h-4 mr-1" /> Ouvrir</Button>
          <Button size="sm" variant="ghost" onClick={() => ouvrirDocument(it, true, apres)} title="Télécharger"><Download className="w-4 h-4" /></Button>
        </div>
      ))}
    </div>
  );
}
