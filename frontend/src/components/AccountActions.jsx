/*
  AccountActions — actions sur un compte (client ou collaborateur), dans les
  listes Clients et Personnels :
    - Désactiver / Réactiver (effet immédiat : plus aucune connexion) ;
    - Réinitialiser le mot de passe (généré ou saisi, affiché UNE fois, à
      transmettre à la personne ; ses sessions ouvertes sont fermées) ;
    - Supprimer (bouton optionnel, selon `canDelete`).
  Et AccountDates : « Dernière connexion » et « Modifié le … par … ».
  API : POST /clients/{id}/active, POST /clients/{id}/reset-password, DELETE /clients/{id}
*/
import React, { useState } from "react";
import { toast } from "sonner";
import { Power, KeyRound, Trash2, Copy } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ui } from "@/components/forms-core/ui";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";

// Date et heure lisibles (« 26/09/2026 14:05 »), ou « Jamais »
export const fmtDateTime = (iso, empty = "Jamais") => {
  if (!iso) return empty;
  try { return new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }); }
  catch { return iso; }
};

// Colonne « Connexion / modification » des listes
export function AccountDates({ account }) {
  return (
    <div className="text-xs leading-tight" data-testid={`account-dates-${account.id}`}>
      <div><span className="text-muted-foreground">Connexion : </span>{fmtDateTime(account.last_login)}</div>
      <div title={account.updated_by_name ? `par ${account.updated_by_name}` : undefined}>
        <span className="text-muted-foreground">Modifié : </span>{fmtDateTime(account.updated_at || account.created_at, "—")}
        {account.updated_by_name && <span className="text-muted-foreground"> · {account.updated_by_name}</span>}
      </div>
    </div>
  );
}

export default function AccountActions({ account, onChanged, canManage = true, canDelete = false, deleteLabel = "ce compte" }) {
  const [openReset, setOpenReset] = useState(false);
  const [openDelete, setOpenDelete] = useState(false);
  const [customPwd, setCustomPwd] = useState("");
  const [newPwd, setNewPwd] = useState(null); // mot de passe à transmettre (affiché une fois)
  const [busy, setBusy] = useState(false);
  const active = account.is_active !== false;

  // Désactiver / réactiver le compte
  const toggleActive = async () => {
    try {
      await apiClient.post(`/clients/${account.id}/active`, { active: !active });
      toast.success(active ? `Compte de ${account.full_name} désactivé` : `Compte de ${account.full_name} réactivé`);
      onChanged?.();
    } catch (err) { toast.error(extractError(err)); }
  };

  // Réinitialiser le mot de passe (saisi, ou généré si le champ est vide)
  const resetPassword = async () => {
    if (customPwd && customPwd.length < 8) { toast.error("8 caractères minimum"); return; }
    setBusy(true);
    try {
      const { data } = await apiClient.post(`/clients/${account.id}/reset-password`, customPwd ? { password: customPwd } : {});
      setNewPwd(data.password);
      onChanged?.();
    } catch (err) { toast.error(extractError(err)); } finally { setBusy(false); }
  };
  const closeReset = () => { setOpenReset(false); setNewPwd(null); setCustomPwd(""); };
  const copyPwd = async () => {
    try { await navigator.clipboard.writeText(newPwd); toast.success("Mot de passe copié"); } catch { toast.error("Copie impossible : sélectionnez-le à la main"); }
  };

  // Supprimer définitivement (confirmation)
  const remove = async () => {
    try {
      await apiClient.delete(`/clients/${account.id}`);
      toast.success(`Compte de ${account.full_name} supprimé`);
      setOpenDelete(false);
      onChanged?.();
    } catch (err) { toast.error(extractError(err)); }
  };

  return (
    <>
      {canManage && (
        <>
          {/* Boutons pleins colorés (design SAWALI) : orange = désactiver, vert = réactiver, bleu = mot de passe */}
          <button type="button" title={active ? "Désactiver le compte" : "Réactiver le compte"} onClick={toggleActive}
            className={`${active ? ui.act.iconAmber : ui.act.iconEmerald} ml-1`} data-testid={`toggle-active-${account.id}`}>
            <Power className="w-3.5 h-3.5" />
          </button>
          <button type="button" title="Réinitialiser le mot de passe" onClick={() => setOpenReset(true)} className={`${ui.act.iconSky} ml-1`} data-testid={`reset-pwd-${account.id}`}>
            <KeyRound className="w-3.5 h-3.5" />
          </button>
        </>
      )}
      {canDelete && (
        <button type="button" className={`${ui.act.iconDanger} ml-1`} title="Supprimer" onClick={() => setOpenDelete(true)} data-testid={`delete-account-${account.id}`}>
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      )}

      {/* Réinitialisation du mot de passe */}
      <Dialog open={openReset} onOpenChange={(v) => { if (!v) closeReset(); }}>
        <DialogContent data-testid="reset-pwd-dialog">
          <DialogHeader><DialogTitle>Réinitialiser le mot de passe</DialogTitle></DialogHeader>
          {!newPwd ? (
            <div className="space-y-3 text-left">
              <p className="text-sm">Compte : <b>{account.full_name}</b> ({account.email}). Ses sessions ouvertes seront fermées.</p>
              <div>
                <Label>Nouveau mot de passe (laisser vide pour en générer un)</Label>
                <Input type="text" value={customPwd} onChange={(e) => setCustomPwd(e.target.value)} placeholder="Généré automatiquement" data-testid="reset-pwd-input" />
              </div>
            </div>
          ) : (
            <div className="space-y-3 text-left" data-testid="reset-pwd-result">
              <p className="text-sm">Nouveau mot de passe de <b>{account.full_name}</b>, à lui transmettre. Il ne sera plus affiché ensuite.</p>
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-md border bg-slate-50 px-3 py-2 text-base select-all" data-testid="reset-pwd-value">{newPwd}</code>
                <Button variant="outline" size="sm" onClick={copyPwd}><Copy className="w-4 h-4 mr-1" />Copier</Button>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={closeReset}>{newPwd ? "Fermer" : "Annuler"}</Button>
            {!newPwd && <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={resetPassword} disabled={busy} data-testid="reset-pwd-confirm">Réinitialiser</Button>}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirmation de suppression */}
      <Dialog open={openDelete} onOpenChange={setOpenDelete}>
        <DialogContent data-testid="delete-account-dialog">
          <DialogHeader><DialogTitle>Supprimer {deleteLabel} ?</DialogTitle></DialogHeader>
          <p className="text-sm text-left">Le compte <b>{account.full_name}</b> ({account.email}) sera supprimé définitivement : la personne ne pourra plus se connecter. La suppression est tracée dans le Journal plateforme.</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpenDelete(false)}>Annuler</Button>
            <Button className="bg-red-600 hover:bg-red-700 text-white" onClick={remove} data-testid="delete-account-confirm">Supprimer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
