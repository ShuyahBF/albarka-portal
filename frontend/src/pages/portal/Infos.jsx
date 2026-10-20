/*
  « Infos » (espace client, lot 54) — un sujet utile par semaine (comptabilité, fiscalité, RH, CNSS) en
  vidéo, audio ou PDF. La plus récente est mise en avant, les précédentes restent consultables.
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";
import GrilleContenus from "@/components/contenus/GrilleContenus";

export default function Infos() {
  const [liste, setListe] = useState(null);
  useEffect(() => {
    apiClient.get("/contenus", { params: { type: "info" } }).then(({ data }) => setListe(data))
      .catch((e) => { toast.error(extractError(e)); setListe([]); });
  }, []);
  return (
    <div className="space-y-5" data-testid="infos-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Mon espace</div>
        <h1 className="font-display text-3xl">Infos utiles</h1>
        <p className="text-muted-foreground mt-1">Chaque semaine, un sujet à connaître : comptabilité, fiscalité, ressources humaines, CNSS.</p>
      </div>
      {liste === null ? <div className="text-sm text-muted-foreground">Chargement…</div>
        : <GrilleContenus contenus={liste} vide="Le premier sujet de la semaine arrive bientôt." />}
    </div>
  );
}
