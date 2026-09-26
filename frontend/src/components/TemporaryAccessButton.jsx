/*
  Bouton « Accès temporaire » (ligne d'un collaborateur, Personnels) — visible
  d'admin et des adresses e-mail désignées par admin. Crée un jeton d'accès
  valable N heures, envoyé au collaborateur par e-mail et WhatsApp : il peut
  alors se connecter hors liste blanche (mot de passe + code toujours demandés).
  API : POST /access/tokens (albarka_access.py)
*/
import React, { useState } from "react";
import { toast } from "sonner";
import { TimerReset, Copy } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ui } from "@/components/forms-core/ui";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";

const DURATIONS = [[4, "4 heures"], [8, "8 heures"], [24, "24 heures"], [72, "3 jours"], [168, "7 jours"]];

export default function TemporaryAccessButton({ account }) {
  const [open, setOpen] = useState(false);
  const [hours, setHours] = useState(24);
  const [note, setNote] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      const { data } = await apiClient.post("/access/tokens", { user_id: account.id, hours, note });
      setResult(data);
    } catch (err) { toast.error(extractError(err)); } finally { setBusy(false); }
  };
  const close = () => { setOpen(false); setResult(null); setNote(""); };
  const copy = async (text) => { try { await navigator.clipboard.writeText(text); toast.success("Copié"); } catch { toast.error("Copie impossible"); } };

  return (
    <>
      {/* Bouton plein violet (design SAWALI) */}
      <button type="button" title="Accès temporaire" onClick={() => setOpen(true)} className={`${ui.act.iconIndigo} ml-1`} data-testid={`temp-access-${account.id}`}>
        <TimerReset className="w-3.5 h-3.5" />
      </button>
      <Dialog open={open} onOpenChange={(v) => { if (!v) close(); }}>
        <DialogContent data-testid="temp-access-dialog">
          <DialogHeader><DialogTitle>Accès temporaire pour {account.full_name}</DialogTitle></DialogHeader>
          {!result ? (
            <div className="space-y-3 text-left">
              <p className="text-sm text-muted-foreground">Le collaborateur pourra se connecter depuis n'importe quel appareil pendant la durée choisie. Il reçoit le lien et le code par e-mail et WhatsApp ; mot de passe et code de vérification restent demandés.</p>
              <div>
                <Label>Durée</Label>
                <select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="mt-1 w-full h-10 rounded-md border px-2 text-sm bg-white" data-testid="temp-access-hours">
                  {DURATIONS.map(([h, l]) => <option key={h} value={h}>{l}</option>)}
                </select>
              </div>
              <div>
                <Label>Message (facultatif)</Label>
                <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} className="mt-1 w-full rounded-md border p-2 text-sm" placeholder="ex. Pour finaliser la clôture annuelle ce week-end" />
              </div>
            </div>
          ) : (
            <div className="space-y-2 text-left text-sm" data-testid="temp-access-result">
              <p>Accès valable jusqu'au <b>{new Date(result.expires_at).toLocaleString("fr-FR")}</b>.</p>
              <p>Envoi : e-mail {result.delivery?.email?.ok ? "✓" : "✗"} · WhatsApp {result.delivery?.whatsapp?.ok ? "✓" : `✗ ${result.delivery?.whatsapp?.error || ""}`}</p>
              <div className="flex items-center gap-2"><code className="flex-1 rounded border bg-slate-50 px-2 py-1 font-mono text-base select-all" data-testid="temp-access-code">{result.code}</code>
                <Button size="sm" variant="outline" onClick={() => copy(result.code)}><Copy className="w-4 h-4" /></Button></div>
              <div className="flex items-center gap-2"><code className="flex-1 rounded border bg-slate-50 px-2 py-1 text-xs break-all select-all">{result.link}</code>
                <Button size="sm" variant="outline" onClick={() => copy(result.link)}><Copy className="w-4 h-4" /></Button></div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={close}>{result ? "Fermer" : "Annuler"}</Button>
            {!result && <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={create} disabled={busy} data-testid="temp-access-create">Créer et envoyer</Button>}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
