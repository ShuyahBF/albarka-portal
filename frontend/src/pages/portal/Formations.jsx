/*
  « Formations » (espace client, lot 54) — formations gratuites ou payantes (mobile money PawaPay).
  Au retour de la page de paiement (?depositId=…&formation=…), le statut est vérifié et l'accès ouvert.
*/
import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";
import GrilleContenus from "@/components/contenus/GrilleContenus";

export default function Formations() {
  const [liste, setListe] = useState(null);
  const [params, setParams] = useSearchParams();

  const charger = useCallback(() => apiClient.get("/contenus", { params: { type: "formation" } })
    .then(({ data }) => setListe(data)).catch((e) => { toast.error(extractError(e)); setListe([]); }), []);
  useEffect(() => { charger(); }, [charger]);

  // Retour du paiement : on vérifie auprès du serveur (qui interroge PawaPay si le webhook tarde)
  useEffect(() => {
    const formation = params.get("formation");
    if (!formation) return;
    apiClient.get(`/contenus/${formation}/statut-achat`).then(({ data }) => {
      if (data.acces) { toast.success("Paiement confirmé : la formation est débloquée."); charger(); }
      else if (data.statut === "failed") toast.error("Le paiement a échoué ou a été annulé.");
      else toast.info("Paiement en cours de confirmation… rechargez la page dans un instant.");
    }).catch(() => {}).finally(() => setParams({}, { replace: true }));
  }, [params, setParams, charger]);

  // Ouvre la page de paiement mobile money
  const acheter = async (c) => {
    const { data } = await apiClient.post(`/contenus/${c.id}/acheter`, {});
    if (data.deja_achete) { toast.success("Déjà acheté"); charger(); return; }
    window.location.href = data.redirect_url;
  };

  return (
    <div className="space-y-5" data-testid="formations-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Mon espace</div>
        <h1 className="font-display text-3xl">Formations</h1>
        <p className="text-muted-foreground mt-1">Se former à la comptabilité, à la fiscalité et à la gestion sociale — gratuitement ou en payant par mobile money.</p>
      </div>
      {liste === null ? <div className="text-sm text-muted-foreground">Chargement…</div>
        : <GrilleContenus contenus={liste} onAcheter={acheter} onChange={charger} vide="Aucune formation disponible pour le moment." />}
    </div>
  );
}
