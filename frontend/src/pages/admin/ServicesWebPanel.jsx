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

const vide = { service: "", mode: "mensuel", montant: "", jour_du_mois: "" };
const LIBELLES_ROLES = { direction: "Direction", secretariat: "Secrétariat", administrateur: "Administrateur", fiscaliste: "Fiscaliste", comptable: "Comptable", aide_comptable: "Aide-comptable", rh: "Ressources humaines", communication: "Communication" };

export default function ServicesWebPanel() {
  const [services, setServices] = useState([]);
  const [nouveau, setNouveau] = useState(vide);
  const [paiement, setPaiement] = useState(null);   // { id, paye_le, montant, reference } : formulaire de paiement ouvert
  const [consultation, setConsultation] = useState({ roles: [], possibles: [] });   // lot 93.1 : rôles qui peuvent consulter (lecture seule)
  const [detail, setDetail] = useState(null);       // lot 94 : id du service dont on gère les paiements (liste, SMS, annulation)
  const [choix, setChoix] = useState([]);              // lot 94 : paiements SMS cochés pour ce service
  const [sms, setSms] = useState(null);             // lot 93 : paiements reçus lus dans les SMS (SAWALI), null = liste fermée
  const [smsOccupe, setSmsOccupe] = useState(false);

  const charger = () => apiClient.get("/admin/services-web").then(({ data }) => setServices(data.services)).catch((e) => toast.error(extractError(e)));
  useEffect(() => { charger(); apiClient.get("/admin/services-web/consultation").then(({ data }) => setConsultation(data)).catch(() => {}); }, []);

  // Création d'un service
  const creer = async () => {
    try {
      await apiClient.post("/admin/services-web", { service: nouveau.service, mode: nouveau.mode, montant: Number(nouveau.montant || 0), jour_du_mois: nouveau.mode === "mensuel" ? Number(nouveau.jour_du_mois) : null });
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

  // Lot 94 — ouvre la gestion des paiements d'un service et charge les paiements reçus par SMS
  const ouvrirDetail = async (s) => { setDetail(s.id); setChoix([]); setPaiement(null); await chargerSms(); };
  const basculerChoix = (id) => setChoix((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  // Utilise les paiements SMS cochés : les montants, dates et références viennent de SAWALI ; un paiement déjà utilisé est refusé
  const utiliserChoix = async () => {
    try { await apiClient.post(`/admin/services-web/${detail}/paiements-sms`, { sms_ids: choix }); toast.success(`${choix.length} paiement(s) SMS utilisé(s)`); setChoix([]); await charger(); await chargerSms(); }
    catch (e) { toast.error(extractError(e)); await chargerSms(); }
  };
  const annulerPaiement = async (p) => {
    if (!window.confirm("Annuler ce paiement ? (un paiement reçu par SMS redevient disponible)")) return;
    try { await apiClient.delete(`/admin/services-web/${detail}/paiements/${p.id}`); await charger(); await chargerSms(); } catch (e) { toast.error(extractError(e)); }
  };

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

      <div className="albarka-card p-4 grid gap-3 sm:grid-cols-5 items-end">
        <div><Label>Service</Label><Input value={nouveau.service} onChange={(e) => setNouveau({ ...nouveau, service: e.target.value })} placeholder="Ex. Hébergement Render" /></div>
        <div><Label>Type de paiement</Label>
          <select className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={nouveau.mode} onChange={(e) => setNouveau({ ...nouveau, mode: e.target.value })} data-testid="select-mode">
            <option value="mensuel">Mensuel (récurrent)</option><option value="unique">Montant unique</option></select></div>
        <div><Label>{nouveau.mode === "unique" ? "Montant total (FCFA)" : "Montant mensuel (FCFA)"}</Label><Input type="number" min={0} value={nouveau.montant} onChange={(e) => setNouveau({ ...nouveau, montant: e.target.value })} /></div>
        {nouveau.mode === "mensuel"
          ? <div><Label>Jour du mois (1 à 31)</Label><Input type="number" min={1} max={31} value={nouveau.jour_du_mois} onChange={(e) => setNouveau({ ...nouveau, jour_du_mois: e.target.value })} placeholder="Ex. 8" data-testid="input-jour-du-mois" /></div>
          : <div className="text-xs text-muted-foreground">Payé en une ou plusieurs fois (ex. 4 × 50 000 F) : le reste à payer est affiché.</div>}
        <Button onClick={creer} disabled={!nouveau.service || (nouveau.mode === "mensuel" && !(Number(nouveau.jour_du_mois) >= 1 && Number(nouveau.jour_du_mois) <= 31)) || (nouveau.mode === "unique" && !(Number(nouveau.montant) > 0))} data-testid="btn-ajouter-service"><Plus className="w-4 h-4 mr-1" /> Ajouter</Button>
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
                <td className="p-3">{s.mode === "unique" ? <span className="text-xs text-muted-foreground">Montant unique</span> : <Input className="w-20" type="number" min={1} max={31} defaultValue={s.jour_du_mois} onBlur={(e) => Number(e.target.value) >= 1 && Number(e.target.value) <= 31 && Number(e.target.value) !== s.jour_du_mois && modifier(s, "jour_du_mois", e.target.value)} />}</td>
                <td className="p-3">{s.payable_avant ? new Date(`${s.payable_avant}T00:00:00`).toLocaleDateString("fr-FR") : "—"}</td>
                <td className="p-3"><EtatService s={s} />{s.mode === "unique" && <div className="text-xs tabular-nums mt-0.5">Reste à payer : <b>{Number(s.reste_a_payer || 0).toLocaleString("fr-FR")}</b> sur {Number(s.montant).toLocaleString("fr-FR")}</div>}</td>
                <td className="p-3 text-xs">{s.dernier_paiement_le ? `${new Date(s.dernier_paiement_le).toLocaleString("fr-FR")} — ${Number(s.dernier_paiement_montant).toLocaleString("fr-FR")} — ${s.dernier_paiement_reference}` : "—"}</td>
                <td className="p-3 text-right whitespace-nowrap">
                  <Button size="sm" variant="outline" onClick={() => { setDetail(null); setPaiement({ id: s.id, paye_le: "", montant: s.mode === "unique" ? "" : s.montant, reference: "" }); }}><Banknote className="w-4 h-4 mr-1" /> Paiement</Button>
                  <Button size="sm" variant="outline" className="ml-1" onClick={() => ouvrirDetail(s)} data-testid={`btn-paiements-${s.id}`}>Paiements SMS</Button>
                  <Button size="sm" variant="ghost" className="text-red-700" onClick={() => supprimer(s)}><Trash2 className="w-4 h-4" /></Button>
                </td>
              </tr>
            ))}
            {services.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-muted-foreground">Aucun service. Ajoutez le premier ci-dessus.</td></tr>}
          </tbody>
        </table>
      </div>

      {/* Lot 94 — paiements d'un service : historique (annulation), sélection de paiements reçus par SMS, reste à payer */}
      {detail && (() => {
        const sv = services.find((x) => x.id === detail);
        if (!sv) return null;
        const choisis = (sms || []).filter((t) => choix.includes(t.id));
        const somme = choisis.reduce((a, t) => a + Number(t.montant), 0);
        const resteApres = sv.mode === "unique" ? Math.max(0, Number(sv.montant) - Number(sv.total_paye || 0) - somme) : null;
        const fm = (v) => `${Number(v || 0).toLocaleString("fr-FR")} ${sv.devise || "FCFA"}`;
        return (
          <div className="albarka-card p-4 space-y-3 border-2 border-emerald-300" data-testid="detail-paiements">
            <div className="flex items-center justify-between gap-2">
              <h3 className="font-semibold">Paiements — {sv.service} {sv.mode === "unique" ? "(montant unique)" : "(mensuel)"}</h3>
              <Button size="sm" variant="ghost" onClick={() => setDetail(null)}>Fermer</Button>
            </div>
            {sv.mode === "unique" && <p className="text-sm tabular-nums">Montant total {fm(sv.montant)} · payé <b>{fm(sv.total_paye)}</b> · reste à payer <b className={sv.reste_a_payer > 0 ? "text-red-700" : "text-green-700"}>{fm(sv.reste_a_payer)}</b></p>}
            <div>
              <p className="text-sm font-medium mb-1">Paiements enregistrés ({(sv.paiements || []).length})</p>
              {(sv.paiements || []).length === 0 ? <p className="text-sm text-muted-foreground">Aucun paiement.</p> : (
                <table className="w-full text-sm tableau"><thead><tr className="text-left border-b"><th className="p-2">Date</th><th className="p-2">Référence</th><th className="p-2">Origine</th><th className="p-2 text-right">Montant</th><th className="p-2" /></tr></thead>
                  <tbody>{sv.paiements.map((p) => (<tr key={p.id} className="border-b last:border-0"><td className="p-2 whitespace-nowrap">{new Date(p.paye_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                    <td className="p-2 font-mono text-xs">{p.reference}</td><td className="p-2 text-xs">{p.source === "sms" ? "SMS reçu" : "Saisi à la main"}</td>
                    <td className="p-2 text-right tabular-nums">{Number(p.montant).toLocaleString("fr-FR")}</td>
                    <td className="p-2 text-right"><button type="button" className="text-xs underline text-red-700" onClick={() => annulerPaiement(p)}>Annuler</button></td></tr>))}</tbody></table>
              )}
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium">Paiements reçus par SMS (comptes associés à ALBARKA dans SAWALI)</p>
              {smsOccupe && <p className="text-sm text-muted-foreground">Chargement…</p>}
              {sms && sms.length === 0 && <p className="text-sm text-muted-foreground">Aucun paiement reçu n'est associé à ALBARKA. Dans SAWALI → Transactions SMS, associez le numéro du payeur à ALBARKA, ou au client de SAWALI lié à ALBARKA.</p>}
              {sms && sms.length > 0 && (
                <div className="overflow-x-auto border rounded">
                  <table className="w-full text-sm tableau"><thead><tr className="text-left border-b"><th className="p-2" /><th className="p-2">Reçu le</th><th className="p-2">De</th><th className="p-2">Référence</th><th className="p-2 text-right">Montant</th></tr></thead>
                    <tbody>{sms.map((t) => (
                      <tr key={t.id} aria-selected={choix.includes(t.id)} className={`border-b last:border-0 ${t.deja_utilise ? "opacity-50" : ""}`}>
                        <td className="p-2"><input type="checkbox" disabled={t.deja_utilise} checked={choix.includes(t.id)} onChange={() => basculerChoix(t.id)} aria-label="Utiliser ce paiement" /></td>
                        <td className="p-2 whitespace-nowrap">{new Date(t.recu_le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                        <td className="p-2">{t.client || t.tiers}{t.numero ? <span className="text-xs text-muted-foreground"> · {t.numero}</span> : null}</td>
                        <td className="p-2 font-mono text-xs">{t.reference_proposee}</td>
                        <td className="p-2 text-right tabular-nums">{Number(t.montant).toLocaleString("fr-FR")}{t.deja_utilise && <div className="text-xs text-muted-foreground">utilisé pour « {t.utilise_par} »</div>}</td>
                      </tr>))}</tbody></table>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-3">
                <Button onClick={utiliserChoix} disabled={choix.length === 0} data-testid="btn-utiliser-sms">Utiliser {choix.length || ""} paiement(s) sélectionné(s)</Button>
                {choix.length > 0 && <span className="text-sm tabular-nums">Sélection : <b>{fm(somme)}</b>{resteApres !== null && <> · reste à payer après : <b>{fm(resteApres)}</b></>}</span>}
              </div>
              <p className="text-xs text-muted-foreground">Un paiement reçu par SMS ne sert qu'une fois : une fois utilisé pour un service, il ne peut plus servir pour un autre (sauf si vous annulez ce paiement ici).</p>
            </div>
          </div>
        );
      })()}

      {/* Lot 93.1 : qui peut CONSULTER (lecture seule, l'option « Mes Services Web » apparaît dans leur menu). Seul le super-admin met à jour les paiements. */}
      <div className="albarka-card p-4 space-y-2" data-testid="consultation">
        <p className="text-sm font-semibold">Qui peut consulter les services web ?</p>
        <p className="text-sm text-muted-foreground">Le DG consulte toujours et reçoit les rappels. Les rôles cochés voient l'option « Mes Services Web » dans leur menu, en lecture seule. Seul le super-admin crée les services et met à jour les paiements.</p>
        <div className="flex flex-wrap gap-x-5 gap-y-1">
          {/* Le DG consulte toujours (et reçoit les rappels) : case cochée et verrouillée */}
          <label className="flex items-center gap-2 text-sm font-medium" title="Le DG consulte toujours et reçoit les rappels"><input type="checkbox" checked disabled data-testid="consultation-dg" />DG (toujours)</label>
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
              ? <p className="text-sm text-muted-foreground">Aucun paiement reçu n'est associé à ALBARKA. Dans SAWALI → Transactions SMS, associez le numéro du payeur à ALBARKA, ou au client de SAWALI lié à ALBARKA.</p>
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
