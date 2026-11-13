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

const vide = { service: "", montant: "", payable_avant: "" };

export default function ServicesWebPanel() {
  const [services, setServices] = useState([]);
  const [nouveau, setNouveau] = useState(vide);
  const [paiement, setPaiement] = useState(null);   // { id, paye_le, montant, reference } : formulaire de paiement ouvert

  const charger = () => apiClient.get("/admin/services-web").then(({ data }) => setServices(data.services)).catch((e) => toast.error(extractError(e)));
  useEffect(() => { charger(); }, []);

  // Création d'un service
  const creer = async () => {
    try {
      await apiClient.post("/admin/services-web", { service: nouveau.service, montant: Number(nouveau.montant || 0), payable_avant: nouveau.payable_avant });
      setNouveau(vide);
      toast.success("Service ajouté");
      charger();
    } catch (e) { toast.error(extractError(e)); }
  };

  // Modification d'une valeur (montant ou échéance) enregistrée à la sortie du champ
  const modifier = async (s, champ, valeur) => {
    try {
      await apiClient.put(`/admin/services-web/${s.id}`, { [champ]: champ === "montant" ? Number(valeur) : valeur });
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

  const supprimer = async (s) => {
    if (!window.confirm(`Supprimer le service « ${s.service} » ?`)) return;
    try { await apiClient.delete(`/admin/services-web/${s.id}`); charger(); } catch (e) { toast.error(extractError(e)); }
  };

  return (
    <div className="space-y-5" data-testid="services-web-panel">
      <p className="text-sm text-muted-foreground max-w-2xl">
        Seul le DG voit ces services (menu « Mes Services Web ») et reçoit les rappels : 7 jours avant, 3 jours avant et le jour même, dans une fenêtre
        qu'il ferme par « J'ai compris ». Après chaque paiement, enregistrez-le ici ; changer l'échéance relance les rappels pour la période suivante.
      </p>

      <div className="albarka-card p-4 grid gap-3 sm:grid-cols-4 items-end">
        <div><Label>Service</Label><Input value={nouveau.service} onChange={(e) => setNouveau({ ...nouveau, service: e.target.value })} placeholder="Ex. Hébergement Render" /></div>
        <div><Label>Montant (FCFA)</Label><Input type="number" min={0} value={nouveau.montant} onChange={(e) => setNouveau({ ...nouveau, montant: e.target.value })} /></div>
        <div><Label>Payable avant le</Label><Input type="date" value={nouveau.payable_avant} onChange={(e) => setNouveau({ ...nouveau, payable_avant: e.target.value })} /></div>
        <Button onClick={creer} disabled={!nouveau.service || !nouveau.payable_avant} data-testid="btn-ajouter-service"><Plus className="w-4 h-4 mr-1" /> Ajouter</Button>
      </div>

      <div className="albarka-card overflow-x-auto">
        <table className="w-full text-sm tableau">
          <thead><tr className="text-left border-b">
            <th className="p-3">Service</th><th className="p-3 text-right">Montant</th><th className="p-3">Payable avant le</th>
            <th className="p-3">État</th><th className="p-3">Dernier paiement</th><th className="p-3 text-right">Actions</th>
          </tr></thead>
          <tbody>
            {services.map((s) => (
              <tr key={s.id} className="border-b last:border-0">
                <td className="p-3 font-medium">{s.service}</td>
                <td className="p-3 text-right"><Input className="w-28 ml-auto text-right tabular-nums" type="number" min={0} defaultValue={s.montant} onBlur={(e) => Number(e.target.value) !== s.montant && modifier(s, "montant", e.target.value)} /></td>
                <td className="p-3"><Input className="w-40" type="date" defaultValue={s.payable_avant} onBlur={(e) => e.target.value && e.target.value !== s.payable_avant && modifier(s, "payable_avant", e.target.value)} /></td>
                <td className="p-3"><EtatService s={s} /></td>
                <td className="p-3 text-xs">{s.dernier_paiement_le ? `${new Date(s.dernier_paiement_le).toLocaleString("fr-FR")} — ${Number(s.dernier_paiement_montant).toLocaleString("fr-FR")} — ${s.dernier_paiement_reference}` : "—"}</td>
                <td className="p-3 text-right whitespace-nowrap">
                  <Button size="sm" variant="outline" onClick={() => setPaiement({ id: s.id, paye_le: "", montant: s.montant, reference: "" })}><Banknote className="w-4 h-4 mr-1" /> Paiement</Button>
                  <Button size="sm" variant="ghost" className="text-red-700" onClick={() => supprimer(s)}><Trash2 className="w-4 h-4" /></Button>
                </td>
              </tr>
            ))}
            {services.length === 0 && <tr><td colSpan={6} className="p-4 text-center text-muted-foreground">Aucun service. Ajoutez le premier ci-dessus.</td></tr>}
          </tbody>
        </table>
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
        </div>
      )}
    </div>
  );
}
