/*
  Lot 72 — Pages « Rapports » et « Ordres de mission » de l'espace client : les documents de cette catégorie que le cabinet a mis à
  disposition du client connecté (API /me/space, uniquement ses documents visibles). Lecture et téléchargement seulement.
  « Rapports » propose aussi le rapport complet de son dossier (PDF généré à la demande : missions, échéances, pièces).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Download, Loader2 } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import ListeDocumentsClient from "@/components/ListeDocumentsClient";

const PAGES = {
  rapport: { titre: "Rapports", intro: "Les rapports établis et signés par le cabinet pour votre dossier.", vide: "Aucun rapport pour l'instant." },
  ordre_mission: { titre: "Ordres de mission", intro: "Les ordres de mission que le cabinet a établis pour vous.", vide: "Aucun ordre de mission pour l'instant." },
};

export default function DocumentsParCategorie({ categorie }) {
  const { user } = useAuth();
  const page = PAGES[categorie];
  const [items, setItems] = useState(null);
  const [telechargement, setTelechargement] = useState(false);

  const charger = useCallback(() => apiClient.get("/me/space")
    .then(({ data }) => setItems((data.items || []).filter((i) => i.category === categorie)))
    .catch((e) => { toast.error(extractError(e)); setItems([]); }), [categorie]);
  useEffect(() => { charger(); }, [charger]);

  // Rapport complet du dossier (PDF) : un client ne peut télécharger que le sien (contrôlé par le serveur)
  const rapportComplet = async () => {
    setTelechargement(true);
    try {
      const res = await apiClient.get(`/reports/client/${user.id}`, { responseType: "blob" });
      const a = document.createElement("a");
      a.href = window.URL.createObjectURL(res.data); a.download = "rapport-albarka.pdf"; document.body.appendChild(a); a.click(); a.remove();
    } catch (err) { toast.error(extractError(err, "Rapport indisponible")); }
    finally { setTelechargement(false); }
  };

  return (
    <div className="space-y-5" data-testid={`page-${categorie}`}>
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Mon espace</div>
        <h1 className="font-display text-3xl">{page.titre}</h1>
        <p className="text-muted-foreground mt-1">{page.intro}</p>
      </div>
      {categorie === "rapport" && (
        <div className="albarka-card p-4 flex flex-wrap items-center gap-3">
          <div className="flex-1 min-w-[220px]">
            <div className="font-medium">Rapport complet de mon dossier</div>
            <div className="text-xs text-muted-foreground">Missions, échéances et pièces, à la date du jour (PDF).</div>
          </div>
          <Button size="sm" variant="outline" onClick={rapportComplet} disabled={telechargement} data-testid="rapport-complet">
            {telechargement ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Download className="w-4 h-4 mr-1" />} Télécharger
          </Button>
        </div>
      )}
      {items === null
        ? <p className="text-sm text-muted-foreground inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Chargement…</p>
        : <ListeDocumentsClient items={items} apres={charger} vide={page.vide} testid={`liste-${categorie}`} />}
    </div>
  );
}
