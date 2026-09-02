import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Save, Send, Building, MessageCircle, Bell, Hash } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

const FIELDS_TABS = ["cabinet", "whatsapp", "notifications", "rapports"];

export default function AdminSettings() {
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testPhone, setTestPhone] = useState("");
  const [wa_new_token, setWaNewToken] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/admin/settings");
      setSettings(data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const save = async (partial) => {
    setSaving(true);
    try {
      const payload = { ...partial };
      // If wa_access_token is masked, do not resend it.
      if (payload.wa_access_token === "********") delete payload.wa_access_token;
      const { data } = await apiClient.put("/admin/settings", payload);
      setSettings(data);
      setWaNewToken("");
      toast.success("Paramètres enregistrés");
    } catch (err) {
      toast.error(extractError(err));
    } finally { setSaving(false); }
  };

  const testWA = async () => {
    if (!testPhone.startsWith("+")) {
      toast.error("Numéro attendu au format international +226…");
      return;
    }
    try {
      const { data } = await apiClient.post("/admin/settings/wa/test", { to: testPhone });
      if (data.ok) toast.success(`WA envoyé (id: ${data.message_id})`);
      else toast.error("Échec envoi WhatsApp — vérifier la config");
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  if (loading || !settings) return <div className="text-muted-foreground">Chargement…</div>;

  return (
    <div className="space-y-6" data-testid="admin-settings-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Paramètres</div>
        <h1 className="font-display text-3xl md:text-4xl text-foreground">
          Administration système
        </h1>
        <p className="text-muted-foreground mt-1 max-w-2xl">
          Configuration du cabinet, WhatsApp Business, notifications et numérotation des rapports.
        </p>
      </div>

      <Tabs defaultValue="cabinet">
        <TabsList data-testid="settings-tabs">
          <TabsTrigger value="cabinet" data-testid="tab-cabinet">
            <Building className="w-4 h-4 mr-1.5" /> Cabinet
          </TabsTrigger>
          <TabsTrigger value="whatsapp" data-testid="tab-whatsapp">
            <MessageCircle className="w-4 h-4 mr-1.5" /> WhatsApp
          </TabsTrigger>
          <TabsTrigger value="notifications" data-testid="tab-notifications">
            <Bell className="w-4 h-4 mr-1.5" /> Notifications
          </TabsTrigger>
          <TabsTrigger value="rapports" data-testid="tab-rapports">
            <Hash className="w-4 h-4 mr-1.5" /> Rapports
          </TabsTrigger>
        </TabsList>

        {/* --- CABINET --- */}
        <TabsContent value="cabinet" className="pt-6">
          <div className="albarka-card p-6 space-y-4 max-w-2xl">
            <div>
              <Label>Nom du cabinet</Label>
              <Input value={settings.cabinet_name || ""} onChange={(e) => setSettings({ ...settings, cabinet_name: e.target.value })} data-testid="cabinet-name-input" />
            </div>
            <div>
              <Label>Email du cabinet</Label>
              <Input type="email" value={settings.cabinet_email || ""} onChange={(e) => setSettings({ ...settings, cabinet_email: e.target.value })} data-testid="cabinet-email-input" />
            </div>
            <div>
              <Label>Téléphone</Label>
              <Input value={settings.cabinet_phone || ""} onChange={(e) => setSettings({ ...settings, cabinet_phone: e.target.value })} data-testid="cabinet-phone-input" />
            </div>
            <div>
              <Label>Adresse</Label>
              <Textarea value={settings.cabinet_address || ""} onChange={(e) => setSettings({ ...settings, cabinet_address: e.target.value })} rows={2} data-testid="cabinet-address-input" />
            </div>
            <Button
              onClick={() => save({
                cabinet_name: settings.cabinet_name,
                cabinet_email: settings.cabinet_email,
                cabinet_phone: settings.cabinet_phone,
                cabinet_address: settings.cabinet_address,
              })}
              disabled={saving}
              className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
              data-testid="save-cabinet-btn"
            >
              <Save className="w-4 h-4 mr-2" />
              Enregistrer
            </Button>
          </div>
        </TabsContent>

        {/* --- WHATSAPP --- */}
        <TabsContent value="whatsapp" className="pt-6">
          <div className="albarka-card p-6 space-y-4 max-w-2xl">
            <div className="flex items-start justify-between">
              <div>
                <div className="font-semibold">WhatsApp Business Cloud API</div>
                <div className="text-sm text-muted-foreground">
                  API officielle Meta Graph — nécessite un WABA, un numéro vérifié et un token.
                </div>
              </div>
              <Switch
                checked={!!settings.wa_enabled}
                onCheckedChange={(v) => setSettings({ ...settings, wa_enabled: v })}
                data-testid="wa-enabled-switch"
              />
            </div>
            <div>
              <Label>Phone Number ID</Label>
              <Input value={settings.wa_phone_number_id || ""} onChange={(e) => setSettings({ ...settings, wa_phone_number_id: e.target.value })} placeholder="ex 1234567890" data-testid="wa-phone-id-input" />
            </div>
            <div>
              <Label>Business Account ID (WABA)</Label>
              <Input value={settings.wa_business_account_id || ""} onChange={(e) => setSettings({ ...settings, wa_business_account_id: e.target.value })} placeholder="ex 987654321" data-testid="wa-waba-id-input" />
            </div>
            <div>
              <Label>Access Token</Label>
              <Input
                type="password"
                value={wa_new_token || (settings.wa_access_token === "********" ? "" : (settings.wa_access_token || ""))}
                onChange={(e) => setWaNewToken(e.target.value)}
                placeholder={settings.wa_access_token === "********" ? "•••••••• (déjà configuré, laisser vide pour ne pas changer)" : "Bearer token Meta Graph"}
                data-testid="wa-token-input"
              />
            </div>
            <div>
              <Label>Graph API version</Label>
              <Input value={settings.wa_graph_version || "v22.0"} onChange={(e) => setSettings({ ...settings, wa_graph_version: e.target.value })} data-testid="wa-graph-version-input" />
            </div>
            <div className="flex gap-3">
              <Button
                onClick={() => save({
                  wa_enabled: settings.wa_enabled,
                  wa_phone_number_id: settings.wa_phone_number_id,
                  wa_business_account_id: settings.wa_business_account_id,
                  wa_graph_version: settings.wa_graph_version,
                  ...(wa_new_token ? { wa_access_token: wa_new_token } : {}),
                })}
                disabled={saving}
                className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
                data-testid="save-wa-btn"
              >
                <Save className="w-4 h-4 mr-2" />
                Enregistrer
              </Button>
            </div>

            <div className="border-t pt-4 mt-4">
              <div className="text-sm font-medium mb-2">Envoyer un message de test</div>
              <div className="flex gap-2">
                <Input placeholder="+226…" value={testPhone} onChange={(e) => setTestPhone(e.target.value)} data-testid="wa-test-phone-input" />
                <Button variant="outline" onClick={testWA} data-testid="wa-test-btn">
                  <Send className="w-4 h-4 mr-2" />
                  Tester
                </Button>
              </div>
            </div>
          </div>
        </TabsContent>

        {/* --- NOTIFICATIONS --- */}
        <TabsContent value="notifications" className="pt-6">
          <div className="albarka-card p-6 space-y-5 max-w-2xl">
            <div className="flex items-start justify-between">
              <div>
                <div className="font-semibold">Alerter les collaborateurs au dépôt d'une pièce</div>
                <div className="text-sm text-muted-foreground">
                  Seuls les comptes actifs autorisés à recevoir des notifications reçoivent l'email.
                </div>
              </div>
              <Switch
                checked={!!settings.notif_upload_enabled}
                onCheckedChange={(v) => setSettings({ ...settings, notif_upload_enabled: v })}
                data-testid="notif-upload-switch"
              />
            </div>
            <div className="flex items-start justify-between">
              <div>
                <div className="font-semibold">Rappels d'échéances</div>
                <div className="text-sm text-muted-foreground">
                  Emails + WhatsApp (si configuré). Le cron tourne chaque matin à 07:00 UTC.
                </div>
              </div>
            </div>
            <div>
              <Label>Nombre de jours avant échéance (séparés par des virgules)</Label>
              <Input
                value={(settings.notif_reminder_days || []).join(", ")}
                onChange={(e) => {
                  const arr = e.target.value.split(",").map((s) => parseInt(s.trim(), 10)).filter((n) => !isNaN(n));
                  setSettings({ ...settings, notif_reminder_days: arr });
                }}
                placeholder="7, 1"
                data-testid="notif-days-input"
              />
              <div className="text-xs text-muted-foreground mt-1">Ex : 7, 3, 1 pour rappeler J-7, J-3 et J-1.</div>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">Notifier aussi les échéances en retard</div>
                <div className="text-sm text-muted-foreground">Rappel quotidien tant que l'échéance n'est pas traitée.</div>
              </div>
              <Switch
                checked={!!settings.notif_overdue}
                onCheckedChange={(v) => setSettings({ ...settings, notif_overdue: v })}
                data-testid="notif-overdue-switch"
              />
            </div>
            <Button
              onClick={() => save({
                notif_upload_enabled: settings.notif_upload_enabled,
                notif_reminder_days: settings.notif_reminder_days,
                notif_overdue: settings.notif_overdue,
              })}
              disabled={saving}
              className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
              data-testid="save-notif-btn"
            >
              <Save className="w-4 h-4 mr-2" />
              Enregistrer
            </Button>
          </div>
        </TabsContent>

        {/* --- RAPPORTS --- */}
        <TabsContent value="rapports" className="pt-6">
          <div className="albarka-card p-6 space-y-4 max-w-2xl">
            <div>
              <Label>Préfixe de numérotation des rapports</Label>
              <Input
                value={settings.report_prefix || "RAP"}
                onChange={(e) => setSettings({ ...settings, report_prefix: e.target.value.toUpperCase().slice(0, 10) })}
                maxLength={10}
                data-testid="report-prefix-input"
              />
              <div className="text-xs text-muted-foreground mt-1">
                Format : <span className="font-mono">{settings.report_prefix || "RAP"}-CLIENT-TYPE-YYYYMM-NNNN</span>
              </div>
            </div>
            <Button
              onClick={() => save({ report_prefix: settings.report_prefix })}
              disabled={saving}
              className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
              data-testid="save-reports-btn"
            >
              <Save className="w-4 h-4 mr-2" />
              Enregistrer
            </Button>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
