/*
  Lot 91/92 — Barre latérale → « Demandes à SAWALI » (DG, Direction, Secrétariat) : liste horodatée des corrections et nouvelles fonctionnalités
  demandées à SAWALI. « Envoyer à SAWALI » remonte les nouvelles demandes ; SAWALI renvoie un numéro, un statut, un commentaire
  et la date de réalisation (ou la date prévue). La zone de recherche, EN HAUT, retrouve aussi les demandes refusées.
  Modification et suppression possibles tant que SAWALI n'a pas validé la demande (réalisée ou refusée).
  API : /demandes-sawali (albarka_demandes_sawali.py)
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Search, Send, Plus, Trash2, RefreshCw, Pencil } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const fmtJour = (d) => (d ? new Date(`${String(d).slice(0, 10)}T00:00:00`).toLocaleDateString("fr-FR") : null);
const COULEUR = { a_remonter: "text-gray-600", remontee: "text-orange-700", realisee: "text-green-700", refusee: "text-red-700" };

// Colonne « Suivi » : réalisée le … / prévue le … / commentaire de SAWALI
function Suivi({ d }) {
  return (
    <div className="space-y-0.5">
      {d.statut === "realisee" && <div className="text-green-700">Réalisée le {fmtJour(d.realisee_le) || "—"}</div>}
      {d.statut === "remontee" && <div className="text-orange-700">{d.prevue_le ? `Prévue le ${fmtJour(d.prevue_le)}` : "Date de réalisation à venir"}</div>}
      {d.commentaire && <div className="text-muted-foreground">{d.commentaire}</div>}
    </div>
  );
}

export default function DemandesSawaliPanel() {
  const [q, setQ] = useState("");
  const [data, setData] = useState({ demandes: [], compteurs: {}, total: 0 });
  const [type, setType] = useState("correction");
  const [texte, setTexte] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [edition, setEdition] = useState(null);   // { id, type, texte } : demande en cours de modification

  const charger = useCallback(() => apiClient.get("/demandes-sawali", { params: { q } }).then(({ data: d }) => setData(d)).catch((e) => toast.error(extractError(e))), [q]);
  useEffect(() => { const t = setTimeout(charger, 250); return () => clearTimeout(t); }, [charger]);   // recherche en direct

  const ajouter = async () => {
    try {
      await apiClient.post("/demandes-sawali", { type, texte });
      setTexte("");
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
      await apiClient.put(`/demandes-sawali/${edition.id}`, { type: edition.type, texte: edition.texte });
      setEdition(null);
      toast.success("Demande modifiée");
      charger();
    } catch (e) { toast.error(extractError(e)); charger(); }
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
  return (
    <div className="space-y-5" data-testid="demandes-sawali-panel">
      {/* Zone de recherche EN HAUT : texte, commentaire, numéro, statut — refusées comprises */}
      <div className="relative max-w-xl">
        <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
        <Input className="pl-9" placeholder="Rechercher une demande (texte, numéro DEM-…, commentaire, « refusée »…)" value={q} onChange={(e) => setQ(e.target.value)} data-testid="demandes-recherche" />
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span>{data.total} demande(s) : {c.a_remonter || 0} à remonter · {c.remontee || 0} en attente · {c.realisee || 0} réalisée(s) · {c.refusee || 0} refusée(s)</span>
        <Button onClick={envoyer} disabled={envoi} data-testid="btn-envoyer-sawali"><Send className="w-4 h-4 mr-1" /> Envoyer à SAWALI</Button>
        <Button variant="outline" onClick={charger}><RefreshCw className="w-4 h-4 mr-1" /> Recharger</Button>
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
          <div><Label>Modifier la demande</Label><Textarea rows={2} value={edition.texte} onChange={(e) => setEdition({ ...edition, texte: e.target.value })} /></div>
          <div className="flex gap-2">
            <Button onClick={enregistrerEdition} disabled={edition.texte.trim().length < 3}>Enregistrer</Button>
            <Button variant="ghost" onClick={() => setEdition(null)}>Annuler</Button>
          </div>
        </div>
      )}

      <div className="albarka-card overflow-x-auto">
        <table className="w-full text-sm tableau">
          <thead><tr className="text-left border-b">
            <th className="p-3">Demandée le</th><th className="p-3">N° SAWALI</th><th className="p-3">Type</th>
            <th className="p-3">Demande</th><th className="p-3">Statut</th><th className="p-3">Suivi</th><th className="p-3" />
          </tr></thead>
          <tbody>
            {data.demandes.map((d) => (
              <tr key={d.id} className="border-b last:border-0 align-top" data-testid={`demande-${d.id}`}>
                <td className="p-3 whitespace-nowrap">{fmt(d.demandee_le)}</td>
                <td className="p-3 font-mono text-xs">{d.numero_sawali || "—"}</td>
                <td className="p-3">{d.type_libelle}</td>
                <td className="p-3 max-w-md">{d.texte}</td>
                <td className={`p-3 font-medium ${COULEUR[d.statut] || ""}`}>{d.statut_libelle}</td>
                <td className="p-3"><Suivi d={d} /></td>
                <td className="p-3 text-right whitespace-nowrap">
                  {(d.statut === "a_remonter" || d.statut === "remontee") && (
                    <>
                      <Button size="sm" variant="ghost" title="Modifier" onClick={() => setEdition({ id: d.id, type: d.type, texte: d.texte })} data-testid={`modifier-${d.id}`}><Pencil className="w-4 h-4" /></Button>
                      <Button size="sm" variant="ghost" title="Supprimer" className="text-red-700" onClick={() => supprimer(d)} data-testid={`supprimer-${d.id}`}><Trash2 className="w-4 h-4" /></Button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {data.demandes.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-muted-foreground">Aucune demande{q ? " pour cette recherche" : ""}.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
