/*
  Lot 45 — pièce jointe d'un message envoyé par le cabinet (document ou image) dans la conversation.
  Image : aperçu ; document : puce avec le nom. Un clic ouvre le fichier dans un nouvel onglet.
  Le fichier est lu avec la session (GET /whatsapp/messages/<id>/fichier), jamais par un lien public.
*/
import React, { useEffect, useState } from "react";
import { FileText, Image as ImageIcon } from "lucide-react";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";

export default function PieceJointeMessage({ message }) {
  const estImage = message.media_kind === "image";
  const [apercu, setApercu] = useState(null);

  // Aperçu des images seulement (les documents ne sont chargés qu'au clic)
  useEffect(() => {
    if (!estImage || !message.fichier_disponible) return undefined;
    let url = null;
    let annule = false;
    apiClient.get(`/whatsapp/messages/${message.id}/fichier`, { responseType: "blob" })
      .then((r) => { if (!annule) { url = URL.createObjectURL(r.data); setApercu(url); } })
      .catch(() => {});
    return () => { annule = true; if (url) URL.revokeObjectURL(url); };
  }, [estImage, message.id, message.fichier_disponible]);

  const ouvrir = async () => {
    if (!message.fichier_disponible) return;
    try {
      const { data } = await apiClient.get(`/whatsapp/messages/${message.id}/fichier`, { responseType: "blob" });
      window.open(URL.createObjectURL(data), "_blank");
    } catch (e) { toast.error(extractError(e, "Ouverture impossible")); }
  };

  return (
    <button type="button" onClick={ouvrir} disabled={!message.fichier_disponible}
            className="mb-1 flex max-w-full items-center gap-2 rounded-md bg-white/15 px-2 py-1.5 text-left text-xs"
            data-testid={`wa-msg-fichier-${message.id}`}>
      {estImage && apercu
        ? <img src={apercu} alt={message.media_filename || "image"} className="max-h-40 max-w-full rounded object-cover" />
        : <>{estImage ? <ImageIcon className="h-4 w-4 shrink-0" /> : <FileText className="h-4 w-4 shrink-0" />}
            <span className="min-w-0 break-all underline">{message.media_filename || "Fichier"}</span></>}
    </button>
  );
}
