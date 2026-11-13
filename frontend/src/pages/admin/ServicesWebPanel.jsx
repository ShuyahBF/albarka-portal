/*
  Lot 90 — Paramètres → « Services Web » (super-admin) : crée et configure les services web du cabinet et met à jour
  leurs informations de paiement. Le DG les voit dans « Mes Services Web » et en reçoit les rappels.
  API : /admin/services-web (albarka_services_web.py)
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Save, Banknote } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EtatService } from "@/pages/admin/MesServicesWeb";

const vide = { service: "", montant: "", jour_du_mois: "" };
const LIBELLES_ROLES = { direction: "Direction", secretariat: "Secrétariat", administrateur: "Administrateur", fiscaliste: "Fiscaliste", comptable: "Comptable", aide_comptable: "Aide-comptable", rh: "Ressources humaines", communication: "Communication" };

export default function ServicesWebPanel() {
  const [services, setServices] = useState([]);
  const [nouveau, setNouveau] = useState(vide);
  const [paiement, setPaiement] = useState(null);   // { id, paye_le, montant, reference } : formulaire de paiement ouvert
  const [consultation, setConsultation] = useState({ roles: [], possibles: [] });   // lot 93.1 : rôles qui peuvent consulter (lecture seule)
  const [sms, setSms] = useState(null);             // lot 93 : paiements reçus lus dans les SMS (SAWALI), null = liste fermée
  const [smsOccupe, setSmsOccupe] = useState(false);

  const charger = () => apiClient.get("/admin/services-web").then(({ data }) => setServices(data.services)).catch((e) => toast.error(extractError(e)));
  useEffect(() => { charger(); apiClient.get("/admin/services-web/consultation").then(({ data }) => setConsultation(data)).catch(() => {}); }, []);

  // Création d'un service
  const creer = async () => {
    try {
      await apiClient.post("/admin/services-web", { service: nouveau.service, montant: Number(nouveau.montant || 0), jour_du_mois: Number(nouveau.jour_du_mois) });
      setNouveau(vide);
      toast.success("Service ajouté");
      charger();
    } catch (e) { toast.error(extractError(e)); }
  };

  // Modification d'une valeur (montant ou échéance) enregistrée à la sortie du champ
  const modifier = async (s, champ, valeur) => {
    try {
      await apiClient.put(`/admin/services-web/${s.id}`, { [champ]: Number(valeur) });
      charger();
    } catch (e) { toast.error(extractError(e)); }
  };

  const enregistrerPaiement = async () => {
    try {
      await apiClient.post(`/admin/services-web/${paiement.id}/paiement`, { paye_le: paiement.paye_le, montant: Number(paiement.montant || 0), reference: paiement.reference });
      setPaiement(null);
      toast.success("Paiement enregistré");
      charger();
    } catch (e) { toast.error(extractError(e)); }
  };

  // Lot 93.1 — coche / décoche un rôle autorisé à consulter ; enregistré tout de suite
  const basculerConsultation = async (role) => {
    const roles = consultation.roles.includes(role) ? consultation.roles.filter((r) => r !== role) : [...consultation.roles, role];
    try { const { data } = await apiClient.put("/admin/services-web/consultation", { roles }); setConsultation((c) => ({ ...c, roles: data.roles })); toast.success("Consultation mise à jour"); }
    catch (e) { toast.error(extractError(e)); }
  };

  // Lot 93 — charge les paiements reçus par SMS (associés à ALBARKA dans SAWALI → Transactions SMS)
  const chargerSms = async () => {
    setSmsOccupe(true);
    try { const { data } = await apiClient.get("/admin/services-web/paiements-sms"); setSms(data.transactions); }
    catch (e) { toast.error(extractError(e)); } finally { setSmsOccupe(false); }
  };
  // Un paiement choisi remplit le formulaire (date et heure, montant, référence) : rien à ressaisir
  const choisirSms = (t) => { setPaiement((p) => ({ ...p, paye_le: t.recu_le, montant: String(t.montant), reference: t.reference_proposee })); setSms(null); };

  const supprimer = async (s) => {
    if (!window.confirm(`Supprimer le service « ${s.service} » ?`)) return;
    try { await apiClient.delete(`/admin/services-web/${s.id}`); charger(); } catch (e) { toast.error(extractError(e)); }
  };

  return (
    <div className="space-y-5" data-testid="services-web-panel">
      <p className="text-sm text-muted-foreground max-w-2xl">
        Seul le DG voit ces services (menu « Mes Services Web ») et reçoit les rappels : 7 jours avant, 3 jours avant et le jour même, dans une fenêtre
        qu'il ferme par « J'ai compris ». Le paiement est MENSUEL : indiquez le jour du mois (ex. le 8) ; ce jour sert d'échéance et de rappel chaque mois
        (le 31 devient le dernier jour des mois plus courts). Après chaque paiement, enregistrez-le ici : le rappel passe au mois suivant.
      </p>

      <div className="albarka-card p-4 grid gap-3 sm:grid-cols-4 items-end">
        <div><Label>Service</Label><Input value={nouveau.service} onChange={(e) => setNouveau({ ...nouveau, service: e.target.value })} placeholder="Ex. Hébergement Render" /></div>
        <div><Label>Montant (FCFA)</Label><Input type="number" min={0} value={nouveau.montant} onChange={(e) => setNouveau({ ...nouveau, montant: e.target.value })} /></div>
        <div><Label>Jour du mois (1 à 31)</Label><Input type="number" min={1} max={31} value={nouveau.jour_du_mois} onChange={(e) => setNouveau({ ...nouveau, jour_du_mois: e.target.value })} placeholder="Ex. 8" data-testid="input-jour-du-mois" /></div>
        <Button onClick={creer} disabled={!nouveau.service || !(Number(nouveau.jour_du_mois) >= 1 && Number(nouveau.jour_du_mois) <= 31)} data-testid="btn-ajouter-service"><Plus className="w-4 h-4 mr-1" /> Ajouter</Button>
      </div>

      <div className="albarka-card overflow-x-auto">
        <table className="w-full text-sm tableau">
          <thead><tr className="text-left border-b">
            <th className="p-3">Service</th><th className="p-3 text-right">Montant</th><th className="p-3">Jour du mois</th><th className="p-3">Prochaine échéance</th>
            <th className="p-3">État</th><th className="p-3">Dernier paiement</th><th className="p-3 text-right">Actions</th>
          </tr></thead>
          <tbody>
            {services.map((s) => (
              <tr key={s.id} className="border-b last:border-0">
                <td className="p-3 font-medium">{s.service}</td>
                <td className="p-3 text-right"><Input className="w-28 ml-auto text-right tabular-nums" type="number" min={0} defaultValue={s.montant} onBlur={(e) => Number(e.target.value) !== s.montant && modifier(s, "montant", e.target.value)} /></td>
                <td className="p-3"><Input className="w-20" type="number" min={1} max={31} defaultValue={s.jour_du_mois} onBlur={(e) => Number(e.target.value) >= 1 && Number(e.target.value) <= 31 && Number(e.target.value) !== s.jour_du_mois && modifier(s, "jour_du_mois", e.target.value)} /></td>
                <td className="p-3">{new Date(`${s.payable_avant}T00:00:00`).toLocaleDateString("fr-FR")}</td>
                <td className="p-3"><EtatService s={s} /></td>
                <td className="p-3 text-xs">{s.dernier_paiement_le ? `${new Date(s.dernier_paiement_le).toLocaleString("fr-FR")} — ${Number(s.dernier_paiement_montant).toLocaleString("fr-FR")} — ${s.dernier_paiement_reference}` : "—"}</td>
                <td className="p-3 text-right whitespace-nowrap">
                  <Button size="sm" variant="outline" onClick={() => setPaiement({ id: s.id, paye_le: "", montant: s.montant, reference: "" })}><Banknote className="w-4 h-4 mr-1" /> Paiement</Button>
                  <Button size="sm" variant="ghost" className="text-red-700" onClick={() => supprimer(s)}><Trash2 className="w-4 h-4" /></Button>
                </td>
              </tr>
            ))}
            {services.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-muted-foreground">Aucun service. Ajoutez le premier ci-dessus.</td></tr>}
          </tbody>
        </table>
      </div>

      {/* Lot 93.1 : qui peut CONSULTER (lecture seule, l'option « Mes Services Web » apparaît dans leur menu). Seul le super-admin met à jour les paiements. */}
      <div className="albarka-card p-4 space-y-2" data-testid="consultation">
        <p className="text-sm font-semibold">Qui peut consulter les services web ?</p>
        <p className="text-sm text-muted-foreground">Le DG consulte toujours et reçoit les rappels. Les rôles cochés voient l'option « Mes Services Web » dans leur menu, en lecture seule. Seul le super-admin crée les services et met à jour les paiements.</p>
        <div className="flex flex-wrap gap-x-5 gap-y-1">
          {consultation.possibles.map((r) => (
            <label key={r} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={consultation.roles.includes(r)} onChange={() => basculerConsultation(r)} />{LIBELLES_ROLES[r] || r}</label>
          ))}
        </div>
      </div>

      {paiement && (
        <div className="albarka-card p-4 grid gap-3 sm:grid-cols-4 items-end" data-testid="form-paiement">
          <div><Label>Payé le (date et heure)</Label><Input type="datetime-local" value={paiement.paye_le} onChange={(e) => setPaiement({ ...paiement, paye_le: e.target.value })} /></div>
          <div><Label>Montant payé</Label><Input type="number" min={0} value={paiement.montant} onChange={(e) => setPaiement({ ...paiement, montant: e.target.value })} /></div>
          <div><Label>Référence de la transaction</Label><Input value={paiement.reference} onChange={(e) => setPaiement({ ...paiement, reference: e.target.value })} /></div>
          <div className="flex gap-2">
            <Button onClick={enregistrerPaiement} disabled={!paiement.paye_le || !paiement.reference}><Save className="w-4 h-4 mr-1" /> Enregistrer</Button>
            <Button variant="ghost" onClick={() => setPaiement(null)}>Annuler</Button>
          </div>
          {/* Lot 93 : choisir un paiement reçu par SMS (SAWALI → Transactions SMS) au lieu de le ressaisir */}
          <div className="sm:col-span-4 space-y-2">
            <Button variant="outline" onClick={chargerSms} disabled={smsOccupe} data-testid="btn-paiements-sms">{smsOccupe ? "Chargement…" : "Choisir un paiement reçu par SMS"}</Button>
            {sms && (sms.length === 0
              ? <p className="text-sm text-muted-foreground">Aucun paiement reçu n'est associé à ALBARKA. Dans SAWALI → Transactions SMS, associez le numéro du payeur à ALBARKA.</p>
              : (
                <div className="overflow-x-auto border rounded" data-testid="liste-paiements-sms">
                  <table className="w-full text-sm tableau">
                    <thead><tr className="text-left border-b"><th className="p-2">Reçu le</th><th className="p-2">De</th><th className="p-2">Référence</th><th className="p-2 text-right">Montant (FCFA)</th><th className="p-2" /></tr></thead>
                    <tbody>{sms.map((t) => (
                      <tr key={t.id} className="border-b last:border-0">
                        <td className="p-2 whitespace-nowrap">{new Date(t.recu_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                        <td className="p-2">{t.client || t.tiers}{t.numero ? <span className="text-xs text-muted-foreground"> · {t.numero}</span> : null}</td>
                        <td className="p-2 font-mono text-xs">{t.reference_proposee}</td>
                        <td className="p-2 text-right tabular-nums">{Number(t.montant).toLocaleString("fr-FR")}</td>
                        <td className="p-2 text-right">{t.deja_enregistre ? <span className="text-xs text-muted-foreground">déjà enregistré</span> : <Button size="sm" onClick={() => choisirSms(t)}>Choisir</Button>}</td>
                      </tr>))}</tbody>
                  </table>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
