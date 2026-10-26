/*
  Lot 72 — Ouvre ou télécharge un document que le cabinet a mis à disposition du client (API /me/space/{source}/{id}/file).
  La première ouverture est notée côté cabinet (le serveur sait que le client l'a consulté). `apres` est rappelé pour rafraîchir la liste.
*/
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";

export async function ouvrirDocument(it, telecharger = false, apres = null) {
  try {
    const res = await apiClient.get(`/me/space/${it.source}/${it.id}/file`, { params: telecharger ? { download: true } : undefined, responseType: "blob" });
    const url = window.URL.createObjectURL(res.data);
    if (telecharger) {
      const a = document.createElement("a");
      a.href = url; a.download = it.filename || "document"; document.body.appendChild(a); a.click(); a.remove();
    } else {
      window.open(url, "_blank");
    }
    if (it.is_new && apres) apres();
  } catch (err) { toast.error(extractError(err, "Ouverture impossible")); }
}
