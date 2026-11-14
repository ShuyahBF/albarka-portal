// recuServiceWeb.js — Lot 96 : REÇU imprimable d'un paiement de service web (ALBARKA).
// Le reçu est construit par le serveur (GET …/paiements/{id}/recu : numéro, service, date, montant, référence, origine, PROCHAINE ÉCHÉANCE ou reste à payer) ;
// ici on le met en page dans une fenêtre cachée et on lance l'impression du navigateur (jamais de téléchargement de fichier).
import { apiClient } from "@/lib/api";

const echapper = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const montant = (v, dev) => `${Number(v || 0).toLocaleString("fr-FR")} ${dev || "FCFA"}`;
const jour = (iso) => (iso ? new Date(`${String(iso).slice(0, 10)}T00:00:00`).toLocaleDateString("fr-FR", { day: "2-digit", month: "long", year: "numeric" }) : "—");
const dateHeure = (iso) => new Date(iso).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" });

/** HTML complet du reçu (testable : fonction pure). */
export function htmlRecu(r) {
  const lignes = [
    ["Service", r.service],
    ["Date du paiement", dateHeure(r.paye_le)],
    ["Référence de la transaction", r.reference || "—"],
    ["Origine du paiement", r.origine],
    ["Montant reçu", montant(r.montant, r.devise)],
  ];
  if (r.mode === "unique") {
    lignes.push(["Montant total du service", montant(r.montant_total, r.devise)], ["Total payé à ce jour", montant(r.total_paye_apres, r.devise)], ["Reste à payer", montant(r.reste_apres, r.devise)]);
  } else {
    lignes.push(["Renouvellement", `chaque ${r.jour_du_mois} du mois`], ["Prochaine échéance", jour(r.prochaine_echeance)]);
  }
  return `<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Reçu ${echapper(r.numero)}</title>
<style>
  body{font-family:Arial,Helvetica,sans-serif;color:#0A1E3D;margin:32px}
  h1{font-size:22px;margin:0 0 4px} .num{color:#475569;font-size:13px;margin-bottom:24px}
  table{width:100%;border-collapse:collapse;font-size:15px} td{padding:10px 8px;border-bottom:1px solid #cbd5e1} td:first-child{color:#475569;width:45%}
  td:last-child{font-weight:600;text-align:right} .echeance td{background:#ecfdf5;border-bottom:2px solid #0F6B4A;font-size:16px}
  .pied{margin-top:40px;font-size:12px;color:#64748b} .sig{margin-top:48px;display:flex;justify-content:space-between;font-size:13px}
</style></head><body>
  <h1>ALBARKA — Reçu de paiement</h1>
  <div class="num">Reçu n° ${echapper(r.numero)} · émis le ${echapper(jour(r.emis_le))}</div>
  <table>${lignes.map(([k, v], i) => `<tr class="${k === "Prochaine échéance" || k === "Reste à payer" ? "echeance" : ""}"><td>${echapper(k)}</td><td>${echapper(v)}</td></tr>`).join("")}</table>
  <div class="sig"><span>Cachet et signature</span><span>${echapper(jour(r.emis_le))}</span></div>
  <div class="pied">Ce reçu atteste le paiement indiqué ci-dessus pour le service web concerné.</div>
</body></html>`;
}

/** Charge le reçu auprès du serveur puis ouvre la boîte d'impression. `chemin` = « /admin/services-web/{id}/paiements/{id}/recu » ou la version « /me/… ». */
export async function imprimerRecu(chemin) {
  const { data } = await apiClient.get(chemin);
  const cadre = document.createElement("iframe");
  cadre.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0";
  document.body.appendChild(cadre);
  cadre.srcdoc = htmlRecu(data);
  await new Promise((ok) => { cadre.onload = ok; });
  cadre.contentWindow.focus();
  cadre.contentWindow.print();
  setTimeout(() => cadre.remove(), 60_000);          // le cadre est retiré après l'impression
}
