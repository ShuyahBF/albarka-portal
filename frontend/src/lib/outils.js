/*
  Outils Numériques (lot 9) — déclenchement d'un téléchargement.
  Le serveur fournit un lien signé, court (2 min) et à usage unique : le
  navigateur l'ouvre directement, sans charger le fichier en mémoire (utile
  pour les gros logiciels). Le serveur enregistre le téléchargement puis
  redirige (lien http) ou relaie le fichier depuis le serveur FTP.
*/
import { toast } from "sonner";
import { API, apiClient, extractError } from "@/lib/api";

export async function downloadTool(tool) {
  // Lien http(s) : il peut mener à une page (boutique d'applications…) ->
  // nouvel onglet ouvert tout de suite, sinon le navigateur le bloque après l'attente.
  const win = tool.protocol === "http" ? window.open("", "_blank") : null;
  try {
    const { data } = await apiClient.post(`/outils-numeriques/${tool.id}/lien`);
    const url = `${API}${data.path}`;
    if (win) {
      win.opener = null;
      win.location.href = url;
      return;
    }
    // Fichier FTP relayé en pièce jointe : la page reste affichée
    const a = document.createElement("a");
    a.href = url;
    a.rel = "noopener";
    a.setAttribute("download", "");
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast.success("Téléchargement lancé");
  } catch (err) {
    if (win) win.close();
    toast.error(extractError(err, "Téléchargement impossible"));
  }
}
