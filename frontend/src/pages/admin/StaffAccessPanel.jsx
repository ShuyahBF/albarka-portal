/*
  Paramètres → « Accès du personnel » (superviseur) — liste blanche :
    - activer / désactiver la liste blanche (désactivée par défaut) ;
    - adresses IP ou plages autorisées (réseau du bureau) ;
    - appareils autorisés (poste partagé du cabinet ou appareil d'un
      collaborateur), demandes d'appareils à approuver ou refuser ;
    - qui peut créer des jetons d'accès temporaires (admin seul le règle) ;
    - jetons d'accès temporaires en cours (révocation).
  Props : settings, setSettings, save(partial), saving (état de AdminSettings)
  API : /access/* (albarka_access.py)
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Save, ShieldCheck, Monitor, Check, X, Trash2, Globe } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { getDeviceId } from "@/lib/device";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");

export default function StaffAccessPanel({ settings, setSettings, save, saving }) {
  const { user } = useAuth();
  const isAdminAccount = (user?.email || "").toLowerCase() === "admin@sawalismartsystems.com";
  const [data, setData] = useState({ devices: [], requests: [] });
  const [tokens, setTokens] = useState([]);
  const [myIp, setMyIp] = useState("");
  const [ipText, setIpText] = useState((settings.staff_ip_whitelist || []).join("\n"));
  const [issuersText, setIssuersText] = useState((settings.access_token_issuer_emails || []).join("\n"));
  const [label, setLabel] = useState("Poste du cabinet");
  const myDevice = getDeviceId();

  const load = () => {
    apiClient.get("/access/devices").then(({ data: d }) => setData(d)).catch(() => {});
    apiClient.get("/access/tokens").then(({ data: d }) => setTokens(d.items || [])).catch(() => {});
  };
  useEffect(() => {
    load();
    apiClient.get("/access/my-ip").then(({ data: d }) => setMyIp(d.ip)).catch(() => {});
  }, []);

  const lines = (t) => t.split(/[\n,;]+/).map((x) => x.trim()).filter(Boolean);
  const saveAccess = () => save({
    staff_whitelist_enabled: !!settings.staff_whitelist_enabled,
    staff_ip_whitelist: lines(ipText),
    ...(isAdminAccount ? { access_token_issuer_emails: lines(issuersText) } : {}),
  });

  // Autoriser l'appareil sur lequel je suis (poste partagé du cabinet)
  const allowThisDevice = async () => {
    try { await apiClient.post("/access/devices", { device_id: myDevice, label, current: true }); toast.success("Cet appareil est autorisé"); load(); }
    catch (err) { toast.error(extractError(err)); }
  };
  const approve = async (r, shared) => {
    try { await apiClient.post(`/access/requests/${r.id}/approve`, { shared }); toast.success(shared ? "Poste partagé autorisé" : `Appareil autorisé pour ${r.user_name}`); load(); }
    catch (err) { toast.error(extractError(err)); }
  };
  const reject = async (r) => { try { await apiClient.post(`/access/requests/${r.id}/reject`); load(); } catch (err) { toast.error(extractError(err)); } };
  const revoke = async (d) => { try { await apiClient.delete(`/access/devices/${d.id}`); toast.success("Appareil retiré"); load(); } catch (err) { toast.error(extractError(err)); } };
  const revokeToken = async (t) => { try { await apiClient.delete(`/access/tokens/${t.id}`); toast.success("Accès temporaire révoqué"); load(); } catch (err) { toast.error(extractError(err)); } };

  const thisDeviceAllowed = data.devices.some((d) => d.device_id === myDevice);

  return (
    <div className="space-y-6 max-w-4xl" data-testid="staff-access-panel">
      {/* Liste blanche : activation + IP */}
      <div className="albarka-card p-6 space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="font-semibold flex items-center gap-2"><ShieldCheck className="w-4 h-4 text-[#0F6B4A]" /> Liste blanche du personnel</div>
            <div className="text-sm text-muted-foreground max-w-xl">
              Activée, un collaborateur ne peut se connecter que depuis une adresse IP ou un appareil autorisé ; sinon il voit « ERREUR 404 »
              après son mot de passe et son code. Admin et le Superviseur ne sont jamais bloqués ; les clients ne sont pas concernés.
              Autorisez d'abord les appareils et le réseau du cabinet, puis activez.
            </div>
          </div>
          <Switch checked={!!settings.staff_whitelist_enabled} onCheckedChange={(v) => setSettings({ ...settings, staff_whitelist_enabled: v })} data-testid="whitelist-switch" />
        </div>
        <div>
          <Label className="flex items-center gap-2"><Globe className="w-4 h-4" /> Adresses IP ou plages autorisées (une par ligne)</Label>
          <textarea rows={3} value={ipText} onChange={(e) => setIpText(e.target.value)} className="mt-1 w-full rounded-md border p-2 text-sm font-mono" placeholder="41.207.12.0/24" data-testid="ip-whitelist" />
          <div className="text-xs text-muted-foreground">
            Votre adresse actuelle : <span className="font-mono">{myIp || "…"}</span>
            {myIp && <button type="button" className="ml-2 text-[#0F6B4A] underline" onClick={() => setIpText((t) => (t ? `${t}\n${myIp}` : myIp))}>ajouter</button>}
            {" "}— utile seulement si le bureau a une adresse fixe (les connexions mobiles changent souvent d'adresse).
          </div>
        </div>
        {/* Qui peut créer des jetons d'accès temporaires (admin seul) */}
        <div>
          <Label>Adresses e-mail autorisées à créer des accès temporaires (en plus d'admin)</Label>
          <textarea rows={2} value={issuersText} onChange={(e) => setIssuersText(e.target.value)} disabled={!isAdminAccount} className="mt-1 w-full rounded-md border p-2 text-sm disabled:bg-slate-50" placeholder="dg@albarka-bf.com" data-testid="issuers-emails" />
          {!isAdminAccount && <div className="text-xs text-amber-700">Seul admin peut modifier cette liste.</div>}
        </div>
        <Button onClick={saveAccess} disabled={saving} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="save-access-btn">
          <Save className="w-4 h-4 mr-2" /> Enregistrer
        </Button>
      </div>

      {/* Appareils autorisés + demandes */}
      <div className="albarka-card p-6 space-y-4">
        <div className="font-semibold flex items-center gap-2"><Monitor className="w-4 h-4 text-[#0F6B4A]" /> Appareils autorisés</div>
        <div className="flex flex-wrap items-end gap-2">
          <div><Label className="text-xs">Nom de cet appareil</Label><Input value={label} onChange={(e) => setLabel(e.target.value)} className="w-56" /></div>
          <Button variant="outline" onClick={allowThisDevice} disabled={thisDeviceAllowed} data-testid="allow-this-device">
            {thisDeviceAllowed ? "Cet appareil est déjà autorisé" : "Autoriser cet appareil (poste partagé)"}
          </Button>
        </div>

        {data.requests.length > 0 && (
          <div>
            <div className="text-sm font-medium mb-1">Demandes en attente ({data.requests.length})</div>
            <div className="space-y-2" data-testid="device-requests">
              {data.requests.map((r) => (
                <div key={r.id} className="border rounded-md p-3 text-sm flex flex-wrap items-center gap-3 bg-amber-50/40">
                  <div className="flex-1 min-w-[220px]">
                    <div className="font-medium">{r.user_name} <span className="text-xs text-muted-foreground">{r.user_email}</span></div>
                    <div className="text-xs text-muted-foreground">{fmt(r.last_attempt_at)} · IP {r.ip || "?"} · {r.attempts || 1} tentative(s)</div>
                    <div className="text-[11px] text-muted-foreground truncate max-w-md">{r.user_agent}</div>
                  </div>
                  <Button size="sm" className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={() => approve(r, false)} data-testid={`approve-${r.id}`}><Check className="w-3.5 h-3.5 mr-1" />Pour ce collaborateur</Button>
                  <Button size="sm" variant="outline" onClick={() => approve(r, true)}>Poste partagé</Button>
                  <Button size="sm" variant="ghost" className="text-red-600" onClick={() => reject(r)}><X className="w-3.5 h-3.5 mr-1" />Refuser</Button>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="trusted-devices">
            <thead><tr className="text-left text-xs text-muted-foreground border-b"><th className="py-2 pr-3">Appareil</th><th className="py-2 pr-3">Pour</th><th className="py-2 pr-3">Dernière utilisation</th><th /></tr></thead>
            <tbody>
              {data.devices.length === 0 && <tr><td colSpan={4} className="py-4 text-center text-muted-foreground">Aucun appareil autorisé.</td></tr>}
              {data.devices.map((d) => (
                <tr key={d.id} className="border-b last:border-0">
                  <td className="py-2 pr-3"><div className="font-medium">{d.label}{d.device_id === myDevice && <span className="ml-2 text-xs text-[#0F6B4A]">(cet appareil)</span>}</div>
                    <div className="text-[11px] text-muted-foreground truncate max-w-xs">{d.user_agent}</div></td>
                  <td className="py-2 pr-3">{d.user_name || "Tout le personnel (poste partagé)"}</td>
                  <td className="py-2 pr-3 tabular-nums">{fmt(d.last_used_at)}</td>
                  <td className="py-2 text-right"><Button size="sm" variant="ghost" className="text-red-600" onClick={() => revoke(d)} title="Retirer"><Trash2 className="w-4 h-4" /></Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Jetons d'accès temporaires */}
      <div className="albarka-card p-6 space-y-3">
        <div className="font-semibold">Accès temporaires</div>
        <div className="text-xs text-muted-foreground">Créés depuis Personnels (bouton « Accès temporaire » sur la ligne du collaborateur) par admin ou une adresse désignée.</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="access-tokens">
            <thead><tr className="text-left text-xs text-muted-foreground border-b"><th className="py-2 pr-3">Collaborateur</th><th className="py-2 pr-3">Créé par</th><th className="py-2 pr-3">Valable jusqu'au</th><th className="py-2 pr-3">Utilisations</th><th /></tr></thead>
            <tbody>
              {tokens.length === 0 && <tr><td colSpan={5} className="py-4 text-center text-muted-foreground">Aucun accès temporaire.</td></tr>}
              {tokens.map((t) => (
                <tr key={t.id} className="border-b last:border-0">
                  <td className="py-2 pr-3">{t.user_name}{t.note && <div className="text-[11px] text-muted-foreground">{t.note}</div>}</td>
                  <td className="py-2 pr-3">{t.created_by_name}</td>
                  <td className="py-2 pr-3 tabular-nums">{fmt(t.expires_at)} {t.active ? <span className="albarka-chip text-[10px] bg-emerald-100 text-emerald-800 ml-1">actif</span> : <span className="albarka-chip text-[10px] bg-slate-100 text-slate-500 ml-1">{t.revoked ? "révoqué" : "expiré"}</span>}</td>
                  <td className="py-2 pr-3">{(t.uses || []).length}</td>
                  <td className="py-2 text-right">{t.active && <Button size="sm" variant="ghost" className="text-red-600" onClick={() => revokeToken(t)}>Révoquer</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
