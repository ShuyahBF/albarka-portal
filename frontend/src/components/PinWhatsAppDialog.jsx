// PinWhatsAppDialog.jsx — Lot 19 : fenêtre « Connexion par WhatsApp » d'un compte (code PIN à 4 chiffres).
// Même fonctionnement que la fenêtre du personnel (lot 16, AdminStaff.jsx), réutilisée pour les CLIENTS :
//   - le PIN est généré par le serveur, affiché UNE seule fois (œil pour l'afficher / le masquer), seul son
//     hachage est enregistré ; un nouveau PIN remplace l'ancien ;
//   - envoi facultatif du PIN par WhatsApp au titulaire ;
//   - « Retirer le PIN » : plus de connexion par WhatsApp pour ce compte.
// Toast « Patientez… » et jauge qui tourne pendant les attentes (règle commune).
import React, { useState } from "react";
import { toast } from "sonner";
import { Eye, EyeOff, KeyRound, Loader2, MessageCircle, Trash2 } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/**
 * cible : compte visé (null = fenêtre fermée) ; etatPin : {defini_le, defini_par_nom} ou undefined ;
 * titulaire : « le client » / « le collaborateur » (textes) ; onFermer() ; onChange() après génération / retrait.
 */
export default function PinWhatsAppDialog({ cible, etatPin, titulaire = "le client", onFermer, onChange }) {
  const [envoiWa, setEnvoiWa] = useState(true);
  const [resultat, setResultat] = useState(null);
  const [visible, setVisible] = useState(true);
  const [occupe, setOccupe] = useState(false);

  const fermer = () => { setResultat(null); setVisible(true); setEnvoiWa(true); onFermer(); };

  // Génère (ou remplace) le PIN : affiché une seule fois
  const generer = async () => {
    setOccupe(true);
    const attente = toast.loading("Patientez… génération du code PIN");
    try {
      const { data } = await apiClient.post(`/staff-pin/${cible.id}`, { envoyer_whatsapp: envoiWa });
      setResultat(data);
      if (data.envoye_whatsapp === false) toast.warning("PIN généré, mais l'envoi WhatsApp a échoué : remettez-le en main propre.", { id: attente });
      else toast.success("Code PIN généré", { id: attente });
      onChange && onChange();
    } catch (err) {
      toast.error(extractError(err), { id: attente });
    } finally { setOccupe(false); }
  };

  // Retire le PIN : plus de connexion par WhatsApp pour ce compte
  const retirer = async () => {
    setOccupe(true);
    const attente = toast.loading("Patientez…");
    try {
      await apiClient.delete(`/staff-pin/${cible.id}`);
      toast.success("Code PIN retiré", { id: attente });
      onChange && onChange();
      fermer();
    } catch (err) {
      toast.error(extractError(err), { id: attente });
    } finally { setOccupe(false); }
  };

  return (
    <Dialog open={!!cible} onOpenChange={(v) => { if (!v) fermer(); }}>
      <DialogContent data-testid="pin-dialog">
        <DialogHeader><DialogTitle>Connexion par WhatsApp — {cible?.full_name}</DialogTitle></DialogHeader>
        {!resultat ? (
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              {titulaire.charAt(0).toUpperCase() + titulaire.slice(1)} se connecte avec son <b>numéro WhatsApp</b> et un
              <b> code PIN à 4 chiffres</b>, puis saisit le code à 6 chiffres reçu par WhatsApp. Le PIN est affiché une seule
              fois ; seul son hachage est enregistré. Un nouveau PIN remplace l'ancien.
            </p>
            <div className="rounded-md border p-2 text-xs">
              Numéro utilisé : <b>{cible?.whatsapp_number || cible?.phone || "aucun — renseignez le WhatsApp (bouton Modifier)"}</b>
              <div className="mt-1">
                État : {etatPin
                  ? <>PIN actif depuis le {new Date(etatPin.defini_le).toLocaleString("fr-FR")}{etatPin.defini_par_nom ? ` (par ${etatPin.defini_par_nom})` : ""}</>
                  : "aucun PIN"}
              </div>
            </div>
            <label className="flex items-center gap-2 cursor-pointer">
              <Checkbox checked={envoiWa} onCheckedChange={(v) => setEnvoiWa(!!v)} data-testid="pin-send-wa" />
              <span className="flex items-center gap-1"><MessageCircle className="w-4 h-4" /> Envoyer aussi le PIN à {titulaire} par WhatsApp</span>
            </label>
          </div>
        ) : (
          <div className="space-y-3 text-sm" data-testid="pin-result">
            <p>Code PIN de <b>{cible?.full_name}</b> (numéro {resultat.numero_whatsapp}) :</p>
            <div className="flex items-center gap-2">
              <span className="font-mono text-3xl tracking-[0.4em] text-[#0B1912]" data-testid="pin-value">{visible ? resultat.pin : "••••"}</span>
              <button type="button" onClick={() => setVisible((v) => !v)}
                className="h-8 w-8 inline-flex items-center justify-center rounded text-muted-foreground hover:text-[#0F6B4A]"
                title={visible ? "Masquer le PIN" : "Afficher le PIN"} aria-label={visible ? "Masquer le PIN" : "Afficher le PIN"}>
                {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {resultat.envoye_whatsapp === true && <p className="text-emerald-700 text-xs">Envoyé par WhatsApp.</p>}
            {resultat.envoye_whatsapp === false && <p className="text-amber-700 text-xs">L'envoi WhatsApp a échoué : remettez ce PIN en main propre.</p>}
            <p className="text-xs text-muted-foreground">Ce PIN ne sera plus jamais affiché. Connexion : page de connexion → « Par WhatsApp ».</p>
          </div>
        )}
        <DialogFooter className="flex-wrap gap-2">
          {!resultat && etatPin && (
            <Button variant="outline" className="text-red-600 mr-auto" onClick={retirer} disabled={occupe} data-testid="pin-remove">
              <Trash2 className="w-4 h-4 mr-2" />Retirer le PIN
            </Button>
          )}
          <Button variant="outline" onClick={fermer}>Fermer</Button>
          {!resultat && (
            <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={generer} disabled={occupe} data-testid="pin-generate">
              {occupe ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <KeyRound className="w-4 h-4 mr-2" />}
              {etatPin ? "Générer un nouveau PIN" : "Générer le PIN"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
