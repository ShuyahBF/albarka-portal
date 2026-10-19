/*
  Lot 41 — boutons « WhatsApp » et « E-mail » : envoient un PDF de paie (bulletin, bulletins du mois,
  livre de paie) au RESPONSABLE de la société (son numéro WhatsApp ou son e-mail).

  Props :
    employerId : société concernée (sert à afficher le destinataire dans la confirmation)
    url        : route d'envoi (POST), ex. /hr/paie/bulletins/<id>/envoyer
    body       : champs en plus du canal (ex. { employer_id, period_month })
    label      : ce qui est envoyé, pour la phrase de confirmation (ex. « Ce bulletin »)

  Déroulement : confirmation avec le nom et le numéro / l'adresse du destinataire ; si le contact n'a pas écrit
  depuis plus de 24 h (WhatsApp), le serveur répond 409 « hors_fenetre_24h » : on demande alors l'accord du cabinet
  (modèle Meta facturé) puis on renvoie avec confirmer_modele = true.
*/
import React, { useState } from "react";
import { toast } from "sonner";
import { MessageCircle, Mail } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";

export default function EnvoiResponsable({ employerId, url, body = {}, label = "Ce document" }) {
  const [busy, setBusy] = useState(false);

  const envoyer = async (canal, confirmer = false) => {
    setBusy(true);
    try {
      // Destinataire affiché dans la confirmation (une seule fois, avant le premier envoi)
      if (!confirmer) {
        const { data: r } = await apiClient.get(`/hr/paie/employeurs/${encodeURIComponent(employerId)}/responsable`);
        const cible = canal === "email" ? r.email : r.whatsapp;
        if (!cible) { toast.error(canal === "email" ? "Aucune adresse e-mail pour le responsable de cette société" : "Aucun numéro WhatsApp pour le responsable de cette société"); return; }
        if (!window.confirm(`${label} sera envoyé en PDF à ${r.nom} (${cible}) par ${canal === "email" ? "e-mail" : "WhatsApp"}. Continuer ?`)) return;
      }
      const { data } = await apiClient.post(url, { ...body, canal, ...(confirmer ? { confirmer_modele: true } : {}) });
      toast.success(`Envoyé à ${data.nom} (${data.to})`);
    } catch (err) {
      const d = err?.response?.data?.detail;
      // 409 : hors fenêtre de 24 h → accord du cabinet pour le modèle Meta facturé
      if (err?.response?.status === 409 && d?.code === "hors_fenetre_24h") {
        if (window.confirm(`${d.message}\n\nEnvoyer quand même (message facturé) ?`)) { setBusy(false); await envoyer(canal, true); return; }
      } else toast.error(extractError(err, "Envoi impossible"));
    } finally { setBusy(false); }
  };

  const bouton = "inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm disabled:opacity-50";
  return (
    <>
      <button type="button" onClick={() => envoyer("whatsapp")} disabled={busy} className={bouton} data-testid="paie-envoyer-whatsapp"
              title="Envoyer le PDF au numéro WhatsApp du responsable de la société"><MessageCircle className="h-4 w-4" /> WhatsApp</button>
      <button type="button" onClick={() => envoyer("email")} disabled={busy} className={bouton} data-testid="paie-envoyer-email"
              title="Envoyer le PDF à l'e-mail du responsable de la société"><Mail className="h-4 w-4" /> E-mail</button>
    </>
  );
}
