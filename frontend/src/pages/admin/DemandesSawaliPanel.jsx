/*
  Lot 91/92 — Barre latérale → « Demandes à SAWALI » (DG, Direction, Secrétariat) : liste horodatée des corrections et nouvelles fonctionnalités
  demandées à SAWALI. « Envoyer à SAWALI » remonte les nouvelles demandes ; SAWALI renvoie un numéro, un statut, un commentaire
  et la date de réalisation (ou la date prévue). La zone de recherche, EN HAUT, retrouve aussi les demandes refusées.
  Modification et suppression possibles tant que SAWALI n'a pas validé la demande (réalisée ou refusée).
  API : /demandes-sawali (albarka_demandes_sawali.py)
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Search, Send, Plus, Trash2, RefreshCw, Pencil, Save, X, Play, OctagonAlert, Clock } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import DetailDemandeModal from "@/components/DetailDemandeModal";   // lot 118 : 20 premiers caractères + « Détails » (modale)
import GanttEnchainement from "@/components/GanttEnchainement";   // lot 118 : enchaînement, points morts des demandes non terminées
import PiecesJointes from "@/components/PiecesJointes";   // lot 120.1 : fichiers joints et annotés
import GanttDemande from "@/components/GanttDemande";   // lot 117 : diagramme de Gantt (dernière colonne)
import { bornesGantt } from "@/lib/ganttDemandes";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const fmtJour = (d) => (d ? new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString("fr-FR") : null);
const COULEUR = { a_remonter: "text-gray-600", remontee: "text-orange-700", en_cours: "text-sky-700", point_mort: "text-slate-900", realisee: "text-green-700", refusee: "text-red-700" };
const PICTO = { remontee: Clock, en_cours: Play, point_mort: OctagonAlert };   // lot 120 : jamais la couleur seule
const UNITE = { jour: "jour(s)", semaine: "semaine(s)", mois: "mois", annee: "an(s)" };
const duree = (d) => (d.duree_valeur && UNITE[d.duree_unite] ? `${d.duree_valeur} ${UNITE[d.duree_unite]}` : null);

// Colonne « Suivi » : réalisée le … / prévue le … / commentaire de SAWALI
function Suivi({ d }) {
  return (
    <div className="space-y-0.5">
      {d.statut === "realisee" && <div className="text-green-700">Réalisée le {fmtJour(d.realisee_le) || "—"}</div>}
      {d.statut === "remontee" && <div className="text-orange-700">{d.prevue_le ? `Prévue le ${fmtJour(d.prevue_le)}` : "Date de réalisation à venir"}</div>}
      {d.statut === "en_cours" && <div className="text-sky-700">{d.prevue_le ? `En cours · fin prévue le ${fmtJour(d.prevue_le)}` : "En cours"}</div>}
      {d.statut === "point_mort" && <div className="text-slate-900">Travail arrêté : voir le commentaire de SAWALI</div>}
      {duree(d) && <div className="text-muted-foreground">Durée estimée : {duree(d)}{d.debut_prevu_le && d.prevue_le ? ` · du ${fmtJour(d.debut_prevu_le)} au ${fmtJour(d.prevue_le)}` : ""}</div>}
      {d.commentaire && <div className="text-muted-foreground">{d.commentaire}</div>}
    </div>
  );
}

export default function DemandesSawaliPanel() {
  const [q, setQ] = useState("");
  const [data, setData] = useState({ demandes: [], compteurs: {}, total: 0 });
  const [type, setType] = useState("correction");
  const [texte, setTexte] = useState("");
  const [pieces, setPieces] = useState([]);       // pièces jointes de la nouvelle demande
  const [envoi, setEnvoi] = useState(false);
  const [edition, setEdition] = useState(null);   // { id, type, texte } : demande en cours de modification

  // Chaque chargement de la liste vaut « page vue » : la pastille de la barre latérale (demandes mises à jour par SAWALI) retombe à zéro tant qu'on est sur cet écran
  const charger = useCallback(() => apiClient.get("/demandes-sawali", { params: { q } }).then(({ data: d }) => { setData(d); apiClient.post("/me/badges/mark-seen", { page: "demandes_sawali" }).catch(() => {}); }).catch((e) => toast.error(extractError(e))), [q]);
  useEffect(() => { const t = setTimeout(charger, 250); return () => clearTimeout(t); }, [charger]);   // recherche en direct

  // Contenu d'une pièce jointe, lu À LA DEMANDE avec la session de l'utilisateur
  const chargerPiece = (d, p) => apiClient.get(`/demandes-sawali/${d.id}/pieces/${p.id}`, { responseType: "blob" }).then((r) => r.data).catch((e) => { toast.error(extractError(e)); throw e; });

  const ajouter = async () => {
    try {
      await apiClient.post("/demandes-sawali", { type, texte, pieces: pieces.map(({ nom, type: t, data }) => ({ nom, type: t, data })) });
      setTexte(""); setPieces([]);
      charger();
    } catch (e) { toast.error(extractError(e)); }
  };
  // Suppression possible tant que SAWALI n'a pas validé (le serveur relaie à SAWALI si la demande est déjà remontée)
  const supprimer = async (d) => {
    if (!window.confirm("Supprimer cette demande ?")) return;
    try { await apiClient.delete(`/demandes-sawali/${d.id}`); charger(); } catch (e) { toast.error(extractError(e)); charger(); }
  };
  // Modification du type et du texte (même règle)
  const enregistrerEdition = async () => {
    try {
      await apiClient.put(`/demandes-sawali/${edition.id}`, { type: edition.type, texte: edition.texte,
        // les pièces ne se modifient que tant que la demande n'est pas partie chez SAWALI
        ...(edition.modifierPieces ? { pieces: (edition.pieces || []).map(({ nom, type: t, data }) => ({ nom, type: t, data })) } : {}) });
      setEdition(null);
      toast.success("Demande modifiée");
      charger();
    } catch (e) { toast.error(extractError(e)); charger(); }
  };
  // Lot 120.5 — TEMPS RÉEL : tant que l'écran est visible, la liste LOCALE est relue toutes les 4 secondes (lecture de notre base seulement) ; SAWALI nous prévient
  // à l'instant d'un traitement (signal signé) et la mise à jour se voit alors presque tout de suite, utile en réunion.
  useEffect(() => {
    const t = setInterval(() => { if (document.visibilityState === "visible") apiClient.get("/demandes-sawali", { params: { q } }).then(({ data: d }) => setData(d)).catch(() => {}); }, 4000);
    return () => clearInterval(t);
  }, [q]);
  // À l'ouverture de l'écran : la relecture lancée à la connexion (en arrière-plan) a pu se terminer entre-temps, on recharge la liste après quelques secondes
  useEffect(() => { const t = setTimeout(charger, 8000); return () => clearTimeout(t); }, [charger]);
  // RAFRAÎCHISSEMENT AUTOMATIQUE : tant que cet écran est ouvert, les statuts sont relus chez SAWALI toutes les 2 minutes (sans rien remonter), puis la liste est rechargée.
  // Le serveur fait aussi cette relecture toutes les 15 minutes même écran fermé.
  useEffect(() => {
    const relire = () => { if (document.visibilityState === "visible") apiClient.post("/demandes-sawali/relire").then(() => charger()).catch(() => {}); };
    const t = setInterval(relire, 120000);
    return () => clearInterval(t);
  }, [charger]);

  // « Actualiser » : interroge SAWALI (statut, commentaire et date des demandes remontées) puis recharge la liste. Avant, le bouton ne relisait que la liste locale :
  // une demande traitée chez SAWALI n'apparaissait qu'au passage du serveur (15 min) ou de la relecture automatique de l'écran (2 min).
  const [relecture, setRelecture] = useState(false);
  const actualiser = async () => {
    setRelecture(true);
    const attente = toast.loading("Actualisation des demandes en cours… (lecture chez SAWALI)");
    try {
      const { data: r } = await apiClient.post("/demandes-sawali/relire");
      await charger();
      toast.success(r.mises_a_jour ? `${r.mises_a_jour} demande(s) mise(s) à jour d'après SAWALI.` : "Demandes relues chez SAWALI : aucun changement.", { id: attente });
    } catch (e) { toast.error(extractError(e), { id: attente }); } finally { setRelecture(false); }
  };

  // Remonte les nouvelles demandes puis relit les numéros, statuts et commentaires
  const envoyer = async () => {
    setEnvoi(true);
    const attente = toast.loading("Patientez… échange avec SAWALI");
    try {
      const { data: r } = await apiClient.post("/demandes-sawali/envoyer");
      toast.success(`${r.envoyees} demande(s) remontée(s), ${r.mises_a_jour} mise(s) à jour`, { id: attente });
      charger();
    } catch (e) { toast.error(extractError(e), { id: attente }); } finally { setEnvoi(false); }
  };

  const c = data.compteurs || {};
  const bornes = bornesGantt(data.demandes);                    // axe du temps COMMUN à toutes les barres du tableau
  return (
    <div className="space-y-5" data-testid="demandes-sawali-panel">
      {/* Lot 118 : vue d'ensemble des demandes NON terminées (enchaînement, points morts) — repliée par défaut */}
      <details open className="rounded-lg border p-3" data-testid="vue-enchainement">
        <summary className="cursor-pointer font-semibold">📈 Enchaînement des demandes non terminées (points morts, retards)</summary>
        <div className="mt-3"><GanttEnchainement demandes={data.demandes} /></div>
      </details>

      {/* Zone de recherche EN HAUT : texte, commentaire, numéro, statut — refusées comprises */}
      <div className="relative max-w-xl">
        <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
        <Input className="pl-9" placeholder="Rechercher une demande (texte, numéro DEM-…, commentaire, « refusée »…)" value={q} onChange={(e) => setQ(e.target.value)} data-testid="demandes-recherche" />
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span>{data.total} demande(s) : {c.a_remonter || 0} à remonter · {c.remontee || 0} en attente · {c.en_cours || 0} en cours · {c.point_mort || 0} point(s) mort(s) · {c.realisee || 0} réalisée(s) · {c.refusee || 0} refusée(s)</span>
        <Button onClick={envoyer} disabled={envoi} data-testid="btn-envoyer-sawali"><Send className="w-4 h-4 mr-1" /> Envoyer à SAWALI</Button>
        <Button variant="outline" onClick={actualiser} disabled={relecture} title="Relire le statut des demandes chez SAWALI" data-testid="btn-actualiser-sawali"><RefreshCw className={`w-4 h-4 mr-1 ${relecture ? "animate-spin" : ""}`} /> Actualiser</Button>
      </div>

      <div className="albarka-card p-4 grid gap-3 sm:grid-cols-[200px_1fr_auto] items-end">
        <div>
          <Label>Type</Label>
          <select className="w-full border rounded-md h-10 px-2 bg-background" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="correction">Correction</option>
            <option value="nouveaute">Nouvelle fonctionnalité</option>
          </select>
        </div>
        <div><Label>Demande</Label><Textarea rows={2} value={texte} onChange={(e) => setTexte(e.target.value)} placeholder="Décrivez la correction ou la fonctionnalité demandée" data-testid="demande-texte" /></div>
        <Button onClick={ajouter} disabled={texte.trim().length < 3} data-testid="btn-ajouter-demande"><Plus className="w-4 h-4 mr-1" /> Ajouter</Button>
        <div className="sm:col-span-3"><PiecesJointes pieces={pieces} onChange={setPieces} /></div>
      </div>

      {edition && (
        <div className="albarka-card p-4 grid gap-3 sm:grid-cols-[200px_1fr_auto] items-end" data-testid="demande-edition">
          <div>
            <Label>Type</Label>
            <select className="w-full border rounded-md h-10 px-2 bg-background" value={edition.type} onChange={(e) => setEdition({ ...edition, type: e.target.value })}>
              <option value="correction">Correction</option>
              <option value="nouveaute">Nouvelle fonctionnalité</option>
            </select>
          </div>
          <div><Label>Modifier la demande</Label><Textarea rows={2} value={edition.texte} onChange={(e) => setEdition({ ...edition, texte: e.target.value })} />
            {edition.aRemonter ? (
              <div className="mt-2 space-y-2">
                <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={edition.modifierPieces} onChange={(e) => setEdition({ ...edition, modifierPieces: e.target.checked })} />Remplacer les pièces jointes actuelles ({edition.nbPieces})</label>
                {edition.modifierPieces && <PiecesJointes pieces={edition.pieces} onChange={(l) => setEdition({ ...edition, pieces: l })} />}
              </div>
            ) : <p className="mt-1 text-xs text-muted-foreground">Les pièces jointes ne se modifient plus une fois la demande envoyée à SAWALI.</p>}
          </div>
          <div className="flex gap-2">
            <Button onClick={enregistrerEdition} disabled={edition.texte.trim().length < 3}><Save className="w-4 h-4 mr-1" /> Enregistrer</Button>
            <Button variant="ghost" onClick={() => setEdition(null)}><X className="w-4 h-4 mr-1" /> Annuler</Button>
          </div>
        </div>
      )}

      <div className="albarka-card overflow-x-auto">
        <table className="w-full text-sm tableau">
          <thead><tr className="text-left border-b">
            <th className="p-3">Demandée le</th><th className="p-3">N° SAWALI</th><th className="p-3">Type</th>
            <th className="p-3">Demande</th><th className="p-3">Statut</th><th className="p-3">Suivi</th><th className="p-3" /><th className="p-3 whitespace-nowrap">Disponibilité estimée</th>
          </tr></thead>
          <tbody>
            {data.demandes.map((d) => (
              <tr key={d.id} className="border-b last:border-0 align-top" data-testid={`demande-${d.id}`}>
                <td className="p-3 whitespace-nowrap">{fmt(d.demandee_le)}</td>
                <td className="p-3 font-mono text-xs">{d.numero_sawali || "—"}</td>
                <td className="p-3">{d.type_libelle}</td>
                <td className="p-3 max-w-md"><DetailDemandeModal d={d} chargerPiece={chargerPiece} />{(d.pieces || []).length > 0 && <span className="ml-1 text-xs text-muted-foreground" title="Pièces jointes">📎 {d.pieces.length}</span>}</td>
                <td className={`p-3 font-medium ${COULEUR[d.statut] || ""}`}>{(() => { const P = PICTO[d.statut]; return <>{P && <P className="mr-1 inline-block h-3.5 w-3.5" aria-hidden="true" />}{d.statut_libelle}</>; })()}</td>
                <td className="p-3"><Suivi d={d} /></td>
                <td className="p-3 text-right whitespace-nowrap">
                  {(d.statut === "a_remonter" || d.statut === "remontee") && (
                    <>
                      <Button size="sm" variant="ghost" title="Modifier" onClick={() => setEdition({ id: d.id, type: d.type, texte: d.texte, modifierPieces: false, pieces: [], aRemonter: d.statut === "a_remonter", nbPieces: (d.pieces || []).length })} data-testid={`modifier-${d.id}`}><Pencil className="w-4 h-4 mr-1" /> Modifier</Button>
                      <Button size="sm" variant="ghost" title="Supprimer" className="text-red-700" onClick={() => supprimer(d)} data-testid={`supprimer-${d.id}`}><Trash2 className="w-4 h-4 mr-1" /> Supprimer</Button>
                    </>
                  )}
                </td>
                <td className="p-3"><GanttDemande demande={d} bornes={bornes} /></td>
              </tr>
            ))}
            {data.demandes.length === 0 && <tr><td colSpan={8} className="p-4 text-center text-muted-foreground">Aucune demande{q ? " pour cette recherche" : ""}.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
