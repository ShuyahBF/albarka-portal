// « Accès au portail » d'un contact (lot 101) : le DG ou le super-administrateur ouvre, modifie, limite dans le temps, révoque ou rétablit l'accès d'un contact d'un client.
// À l'ouverture, un mot de passe PROVISOIRE est montré UNE SEULE FOIS (à transmettre au contact) ; le contact peut ensuite se connecter comme un client.
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { CalendarX, Copy, KeyRound, Save, ShieldOff, ShieldCheck, X } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export default function AccesContact({ contact, onFermer }) {
  const [fonctions, setFonctions] = useState([]);
  const [acces, setAcces] = useState(null);               // { ouvert, actif, motif, fonction, acces_jusqua, revoque, email, derniere_connexion }
  const [fonction, setFonction] = useState(contact.function || "autre");
  const [fin, setFin] = useState("");
  const [provisoire, setProvisoire] = useState("");       // montré une seule fois

  const charger = useCallback(async () => {
    try {
      const [f, a] = await Promise.all([apiClient.get("/fonctions-contacts"), apiClient.get(`/contacts/${contact.id}/acces`)]);
      setFonctions(f.data.fonctions); setAcces(a.data);
      if (a.data.ouvert) { setFonction(a.data.fonction); setFin(a.data.acces_jusqua || ""); }
    } catch (err) { toast.error(extractError(err)); }
  }, [contact.id]);
  useEffect(() => { charger(); }, [charger]);

  const agir = async (requete, message) => {
    try { const { data } = await requete(); if (data?.mot_de_passe_provisoire) setProvisoire(data.mot_de_passe_provisoire); toast.success(message); await charger(); }
    catch (err) { toast.error(extractError(err)); }
  };
  const ouvrir = () => agir(() => apiClient.post(`/contacts/${contact.id}/acces`, { fonction, acces_jusqua: fin || null }), "Accès ouvert");
  const enregistrer = () => agir(() => apiClient.put(`/contacts/${contact.id}/acces`, { fonction, acces_jusqua: fin || undefined, efface_date: !fin }), "Accès modifié (enregistré)");
  const revoquer = () => window.confirm(`Révoquer l'accès de ${contact.full_name} ? Sa prochaine action sera refusée.`) && agir(() => apiClient.delete(`/contacts/${contact.id}/acces`), "Accès révoqué");
  const retablir = () => agir(() => apiClient.put(`/contacts/${contact.id}/acces`, { revoque: false }), "Accès rétabli");

  const copier = async () => { try { await navigator.clipboard.writeText(provisoire); toast.success("Mot de passe provisoire copié"); } catch { toast.error("Copie impossible : recopiez-le à la main"); } };

  return (
    <Dialog open onOpenChange={(o) => !o && onFermer()}>
      <DialogContent className="max-h-[85dvh] max-w-md overflow-y-auto" data-testid="acces-contact">
        <DialogHeader><DialogTitle className="flex items-center gap-2"><KeyRound className="h-5 w-5 text-[#0B4F8A]" />Accès au portail : {contact.full_name}</DialogTitle></DialogHeader>
        {!acces && <p className="py-6 text-center text-muted-foreground">Chargement…</p>}
        {acces && (
          <div className="space-y-4">
            {acces.ouvert && (
              <p className={`rounded-lg p-3 text-sm ${acces.actif ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-900"}`} data-testid="acces-etat">
                {acces.actif ? <><ShieldCheck className="mr-1 inline h-4 w-4" />Accès actif{acces.acces_jusqua ? ` jusqu'au ${new Date(acces.acces_jusqua).toLocaleDateString("fr-FR")}` : " (sans date de fin)"}.</> : <><ShieldOff className="mr-1 inline h-4 w-4" />{acces.motif}</>}
                <span className="block text-xs opacity-80">Identifiant : {acces.email}{acces.derniere_connexion ? ` · dernière connexion ${new Date(acces.derniere_connexion).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}` : " · jamais connecté"}</span>
              </p>
            )}
            {!acces.ouvert && !contact.email && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Ce contact n'a pas d'adresse e-mail : elle sert d'identifiant. Ajoutez-la d'abord.</p>}
            <div>
              <Label>Fonction (profil d'accès)</Label>
              <Select value={fonction} onValueChange={setFonction}>
                <SelectTrigger data-testid="acces-fonction"><SelectValue /></SelectTrigger>
                <SelectContent>{fonctions.map((f) => <SelectItem key={f.code} value={f.code}>{f.libelle}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label>Accès jusqu'au (facultatif)</Label>
              <div className="flex gap-2">
                <Input type="date" value={fin} onChange={(e) => setFin(e.target.value)} data-testid="acces-fin" />
                {fin && <Button variant="outline" onClick={() => setFin("")} title="Sans date de fin" aria-label="Effacer la date de fin"><CalendarX className="h-4 w-4" /></Button>}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">L'accès cesse à la fin de ce jour. Vide = sans limite.</p>
            </div>
            {provisoire && (
              <div className="rounded-lg border-2 border-amber-400 bg-amber-50 p-3" data-testid="acces-provisoire">
                <p className="text-sm font-semibold text-amber-900">Mot de passe provisoire (affiché une seule fois)</p>
                <div className="mt-1 flex items-center gap-2"><code className="flex-1 rounded bg-white px-2 py-1 text-lg tracking-wider">{provisoire}</code><Button variant="outline" size="sm" onClick={copier} title="Copier" aria-label="Copier le mot de passe"><Copy className="h-4 w-4" /></Button></div>
                <p className="mt-1 text-xs text-amber-900">Transmettez-le au contact : il se connecte avec son e-mail, ce mot de passe, puis le code reçu.</p>
              </div>
            )}
          </div>
        )}
        <DialogFooter className="flex-wrap gap-2">
          <Button variant="outline" onClick={onFermer}><X className="mr-1 h-4 w-4" />Fermer</Button>
          {acces && !acces.ouvert && <Button onClick={ouvrir} disabled={!contact.email} className="bg-[#0F6B4A] text-white hover:bg-[#0A4E36]" data-testid="acces-ouvrir"><KeyRound className="mr-1 h-4 w-4" />Ouvrir l'accès</Button>}
          {acces?.ouvert && <Button onClick={enregistrer} className="bg-[#0F6B4A] text-white hover:bg-[#0A4E36]" data-testid="acces-enregistrer"><Save className="mr-1 h-4 w-4" />Enregistrer</Button>}
          {acces?.ouvert && !acces.revoque && <Button variant="outline" onClick={revoquer} className="border-red-300 text-red-700" data-testid="acces-revoquer"><ShieldOff className="mr-1 h-4 w-4" />Révoquer</Button>}
          {acces?.ouvert && acces.revoque && <Button variant="outline" onClick={retablir} data-testid="acces-retablir"><ShieldCheck className="mr-1 h-4 w-4" />Rétablir</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
