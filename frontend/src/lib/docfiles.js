/*
  docfiles — ouverture / téléchargement des fichiers protégés (PDF, Word, Excel)
  produits par le serveur (lot 7). La requête passe par apiClient (jeton de
  connexion), puis le fichier s'ouvre dans un nouvel onglet ou se télécharge.
*/
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";

// method "get" ou "post" ; data = corps JSON (post) ; params = paramètres d'adresse
export async function openServerFile(url, { method = "get", data, params, filename, download = false, type = "application/pdf" } = {}) {
  // Onglet ouvert tout de suite (sinon le navigateur le bloque après l'attente)
  const win = download ? null : window.open("", "_blank");
  try {
    const res = method === "post"
      ? await apiClient.post(url, data || {}, { params, responseType: "blob" })
      : await apiClient.get(url, { params, responseType: "blob" });
    const href = window.URL.createObjectURL(new Blob([res.data], { type: res.headers?.["content-type"] || type }));
    if (download) {
      const a = document.createElement("a");
      a.href = href; a.download = filename || "document";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => window.URL.revokeObjectURL(href), 3000);
    } else if (win) {
      win.location.href = href;
    } else {
      window.open(href, "_blank");
    }
  } catch (err) {
    if (win) win.close();
    // Le message d'erreur du serveur arrive sous forme de blob : on le relit
    let msg = extractError(err, "Échec de l'ouverture du fichier");
    try {
      const txt = await err?.response?.data?.text?.();
      if (txt) msg = JSON.parse(txt).detail || msg;
    } catch { /* message par défaut */ }
    toast.error(msg);
  }
}
