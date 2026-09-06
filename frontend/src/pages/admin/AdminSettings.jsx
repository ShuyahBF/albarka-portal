import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Save, Send, Building, MessageCircle, Bell, Hash, KeyRound, Image as ImageIcon, CreditCard } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import CertificatesPanel from "@/pages/admin/CertificatesPanel";
import BrandingPanel from "@/pages/admin/BrandingPanel";
import { useAuth } from "@/contexts/AuthContext";

const FIELDS_TABS = ["cabinet", "whatsapp", "notifications", "rapports"];

export default function AdminSettings() {
  const { user } = useAuth();
  const isAdministrateur = (user?.roles || []).includes("administrateur");
  const [settings, setSettings] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testPhone, setTestPhone] = useState("");
  const [wa_new_token, setWaNewToken] = useState("");
  const [recaptchaNewSecret, setRecaptchaNewSecret] = useState("");
  const [pawapaySandboxNewToken, setPawapaySandboxNewToken] = useState("");
  const [pawapayProductionNewToken, setPawapayProductionNewToken] = useState("");

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
      // If wa_access_token / recaptcha_secret_key / jetons PawaPay sont masqués, ne pas les renvoyer.
      if (payload.wa_access_token === "********") delete payload.wa_access_token;
      if (payload.recaptcha_secret_key === "********") delete payload.recaptcha_secret_key;
      if (payload.pawapay_api_token_sandbox === "********") delete payload.pawapay_api_token_sandbox;
      if (payload.pawapay_api_token_production === "********") delete payload.pawapay_api_token_production;
      const { data } = await apiClient.put("/admin/settings", payload);
      setSettings(data);
      setWaNewToken("");
      setRecaptchaNewSecret("");
      setPawapaySandboxNewToken("");
      setPawapayProductionNewToken("");
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
          <TabsTrigger value="branding" data-testid="tab-branding">
            <ImageIcon className="w-4 h-4 mr-1.5" /> Branding
          </TabsTrigger>
          <TabsTrigger value="signature" data-testid="tab-signature">
            <KeyRound className="w-4 h-4 mr-1.5" /> Signature
          </TabsTrigger>
          <TabsTrigger value="paiements" data-testid="tab-paiements">
            <CreditCard className="w-4 h-4 mr-1.5" /> Paiements
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
              <Label>Email de contact</Label>
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

            <div className="border-t pt-4 mt-4">
              <div className="text-sm font-semibold mb-1">Domaine d'expédition email</div>
              <div className="text-xs text-muted-foreground mb-3">
                Une fois votre domaine vérifié chez Resend, indiquez ici l'adresse expéditrice
                (ex&nbsp;: <span className="font-mono">noreply@albarka-bf.com</span>).
                Sans ce champ, les emails partent depuis l'adresse générique de la plateforme.
              </div>
              <Label>Adresse d'expéditeur (from)</Label>
              <Input
                value={settings.email_from_address || ""}
                onChange={(e) => setSettings({ ...settings, email_from_address: e.target.value })}
                placeholder="noreply@votre-domaine.bf"
                data-testid="email-from-input"
              />
              <div className="mt-2"><Label>Adresse de réponse (reply-to)</Label>
                <Input
                  value={settings.email_reply_to || ""}
                  onChange={(e) => setSettings({ ...settings, email_reply_to: e.target.value })}
                  placeholder="contact@votre-domaine.bf"
                  data-testid="email-replyto-input"
                />
              </div>
              <div className="mt-2 text-xs text-muted-foreground">
                Étapes de vérification&nbsp;:
                <ol className="list-decimal ml-4 mt-1 space-y-0.5">
                  <li>Ouvrir <a href="https://resend.com/domains" className="underline" target="_blank" rel="noreferrer">resend.com/domains</a></li>
                  <li>Ajouter votre domaine, copier les enregistrements DNS (SPF, DKIM, DMARC)</li>
                  <li>Ajouter les enregistrements chez votre registrar (Cloudflare, OVH…)</li>
                  <li>Une fois « Verified », renseigner l'adresse ci-dessus</li>
                </ol>
              </div>
            </div>

            <Button
              onClick={() => save({
                cabinet_name: settings.cabinet_name,
                cabinet_email: settings.cabinet_email,
                cabinet_phone: settings.cabinet_phone,
                cabinet_address: settings.cabinet_address,
                email_from_address: settings.email_from_address,
                email_reply_to: settings.email_reply_to,
              })}
              disabled={saving}
              className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
              data-testid="save-cabinet-btn"
            >
              <Save className="w-4 h-4 mr-2" />
              Enregistrer
            </Button>

            <div className="border-t pt-4 mt-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-semibold">RGPD — masquer les numéros clients</div>
                  <div className="text-sm text-muted-foreground max-w-md">
                    Une fois activé, seuls Administrateur/Superviseur/DG/Direction/Secrétariat
                    voient les numéros de téléphone et WhatsApp des clients en clair — les autres
                    collaborateurs les voient masqués. Réservé au rôle Administrateur.
                  </div>
                </div>
                <Switch
                  checked={!!settings.rgpd_masking_enabled}
                  onCheckedChange={(v) => setSettings({ ...settings, rgpd_masking_enabled: v })}
                  disabled={!isAdministrateur}
                  data-testid="rgpd-masking-switch"
                />
              </div>
              {!isAdministrateur && (
                <div className="text-xs text-amber-700 mt-2">
                  Seul un compte Administrateur peut modifier ce réglage.
                </div>
              )}
              {isAdministrateur && (
                <Button
                  onClick={() => save({ rgpd_masking_enabled: settings.rgpd_masking_enabled })}
                  disabled={saving}
                  variant="outline"
                  className="mt-3"
                  data-testid="save-rgpd-btn"
                >
                  <Save className="w-4 h-4 mr-2" />
                  Enregistrer le RGPD
                </Button>
              )}
            </div>

            <div className="border-t pt-4 mt-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="font-semibold">reCAPTCHA — page de connexion</div>
                  <div className="text-sm text-muted-foreground max-w-md">
                    Widget Google « je ne suis pas un robot » (reCAPTCHA v2) affiché sur la
                    page de connexion. Nécessite une paire clé de site / clé secrète créée sur
                    la console Google reCAPTCHA.
                  </div>
                </div>
                <Switch
                  checked={!!settings.recaptcha_enabled}
                  onCheckedChange={(v) => setSettings({ ...settings, recaptcha_enabled: v })}
                  data-testid="recaptcha-enabled-switch"
                />
              </div>
              <div className="mt-3 space-y-3">
                <div>
                  <Label>Clé de site (publique)</Label>
                  <Input
                    value={settings.recaptcha_site_key || ""}
                    onChange={(e) => setSettings({ ...settings, recaptcha_site_key: e.target.value })}
                    placeholder="6Lc..."
                    data-testid="recaptcha-site-key-input"
                  />
                </div>
                <div>
                  <Label>Clé secrète</Label>
                  <Input
                    type="password"
                    value={recaptchaNewSecret || (settings.recaptcha_secret_key === "********" ? "" : (settings.recaptcha_secret_key || ""))}
                    onChange={(e) => setRecaptchaNewSecret(e.target.value)}
                    placeholder={settings.recaptcha_secret_key === "********" ? "•••••••• (déjà configurée, laisser vide pour ne pas changer)" : "6Lc..."}
                    data-testid="recaptcha-secret-key-input"
                  />
                </div>
              </div>
              <Button
                onClick={() => save({
                  recaptcha_enabled: settings.recaptcha_enabled,
                  recaptcha_site_key: settings.recaptcha_site_key,
                  ...(recaptchaNewSecret ? { recaptcha_secret_key: recaptchaNewSecret } : {}),
                })}
                disabled={saving}
                variant="outline"
                className="mt-3"
                data-testid="save-recaptcha-btn"
              >
                <Save className="w-4 h-4 mr-2" />
                Enregistrer le reCAPTCHA
              </Button>
            </div>
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

            <div className="border-t pt-4 mt-4 space-y-4">
              <div className="text-sm font-semibold">Filigrane &amp; QR code sur les documents envoyés</div>
              <div className="text-xs text-muted-foreground -mt-2">
                Appliqué sur une copie temporaire juste avant l'envoi (photo ou PDF) — le fichier
                d'origine stocké n'est jamais modifié. Les deux réglages s'activent indépendamment.
              </div>

              <div className="flex items-start justify-between">
                <div>
                  <div className="font-medium">Filigrane texte</div>
                  <div className="text-sm text-muted-foreground">Variables disponibles : {"{cabinet}"} et {"{date}"}.</div>
                </div>
                <Switch
                  checked={!!settings.wa_watermark_enabled}
                  onCheckedChange={(v) => setSettings({ ...settings, wa_watermark_enabled: v })}
                  data-testid="wa-watermark-switch"
                />
              </div>
              <Input
                value={settings.wa_watermark_text || ""}
                onChange={(e) => setSettings({ ...settings, wa_watermark_text: e.target.value })}
                placeholder="{cabinet} — {date}"
                disabled={!settings.wa_watermark_enabled}
                data-testid="wa-watermark-text-input"
              />

              <div className="flex items-start justify-between pt-2">
                <div>
                  <div className="font-medium">QR code</div>
                  <div className="text-sm text-muted-foreground">Contenu fixe encodé (lien du cabinet, numéro, etc.).</div>
                </div>
                <Switch
                  checked={!!settings.wa_qr_enabled}
                  onCheckedChange={(v) => setSettings({ ...settings, wa_qr_enabled: v })}
                  data-testid="wa-qr-switch"
                />
              </div>
              <Input
                value={settings.wa_qr_content || ""}
                onChange={(e) => setSettings({ ...settings, wa_qr_content: e.target.value })}
                placeholder="https://albarka-bf.com"
                disabled={!settings.wa_qr_enabled}
                data-testid="wa-qr-content-input"
              />

              <Button
                onClick={() => save({
                  wa_watermark_enabled: settings.wa_watermark_enabled,
                  wa_watermark_text: settings.wa_watermark_text,
                  wa_qr_enabled: settings.wa_qr_enabled,
                  wa_qr_content: settings.wa_qr_content,
                })}
                disabled={saving}
                variant="outline"
                data-testid="save-wa-stamp-btn"
              >
                <Save className="w-4 h-4 mr-2" />
                Enregistrer filigrane/QR
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
            <div className="flex items-start justify-between pl-4 border-l-2 border-[#0F6B4A]/30">
              <div>
                <div className="font-medium">Alerter aussi par WhatsApp</div>
                <div className="text-sm text-muted-foreground">
                  Message WA envoyé à chaque collaborateur ayant un numéro renseigné.
                </div>
              </div>
              <Switch
                checked={!!settings.notif_upload_wa}
                onCheckedChange={(v) => setSettings({ ...settings, notif_upload_wa: v })}
                data-testid="notif-upload-wa-switch"
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
                notif_upload_wa: settings.notif_upload_wa,
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

        {/* --- BRANDING --- */}
        <TabsContent value="branding" className="pt-6">
          <BrandingPanel />
        </TabsContent>

        {/* --- SIGNATURE --- */}
        <TabsContent value="signature" className="pt-6">
          <CertificatesPanel />
        </TabsContent>

        {/* --- PAIEMENTS (PawaPay) --- */}
        <TabsContent value="paiements" className="pt-6">
          <div className="albarka-card p-6 space-y-4 max-w-2xl">
            <div className="flex items-start justify-between">
              <div>
                <div className="font-semibold">PawaPay — mobile money</div>
                <div className="text-sm text-muted-foreground">
                  Liens de paiement Orange/Moov/Telecel générés depuis le module Paiements (rôle Caissier).
                </div>
              </div>
              <Switch
                checked={!!settings.pawapay_enabled}
                onCheckedChange={(v) => setSettings({ ...settings, pawapay_enabled: v })}
                data-testid="pawapay-enabled-switch"
              />
            </div>
            <div>
              <Label>Environnement</Label>
              <select
                className="w-full h-9 text-sm rounded-md border border-input bg-background px-3"
                value={settings.pawapay_environment || "sandbox"}
                onChange={(e) => setSettings({ ...settings, pawapay_environment: e.target.value })}
                data-testid="pawapay-environment-select"
              >
                <option value="sandbox">Sandbox (test)</option>
                <option value="production">Production</option>
              </select>
            </div>
            <div>
              <Label>Jeton API — Sandbox</Label>
              <Input
                type="password"
                value={pawapaySandboxNewToken || (settings.pawapay_api_token_sandbox === "********" ? "" : (settings.pawapay_api_token_sandbox || ""))}
                onChange={(e) => setPawapaySandboxNewToken(e.target.value)}
                placeholder={settings.pawapay_api_token_sandbox === "********" ? "•••••••• (déjà configuré, laisser vide pour ne pas changer)" : "Jeton sandbox PawaPay"}
                data-testid="pawapay-sandbox-token-input"
              />
            </div>
            <div>
              <Label>Jeton API — Production</Label>
              <Input
                type="password"
                value={pawapayProductionNewToken || (settings.pawapay_api_token_production === "********" ? "" : (settings.pawapay_api_token_production || ""))}
                onChange={(e) => setPawapayProductionNewToken(e.target.value)}
                placeholder={settings.pawapay_api_token_production === "********" ? "•••••••• (déjà configuré, laisser vide pour ne pas changer)" : "Jeton production PawaPay"}
                data-testid="pawapay-production-token-input"
              />
            </div>
            <div>
              <Label>Pays (ISO-3)</Label>
              <Input
                value={settings.pawapay_country || "BFA"}
                onChange={(e) => setSettings({ ...settings, pawapay_country: e.target.value.toUpperCase() })}
                maxLength={3} data-testid="pawapay-country-input"
              />
            </div>
            <div>
              <Label>Secret du webhook de callback</Label>
              <Input
                value={settings.pawapay_callback_secret || ""}
                onChange={(e) => setSettings({ ...settings, pawapay_callback_secret: e.target.value })}
                placeholder="Chaîne aléatoire utilisée dans l'URL du webhook PawaPay"
                data-testid="pawapay-callback-secret-input"
              />
              {settings.pawapay_callback_secret && (
                <div className="text-xs text-muted-foreground mt-1 font-mono break-all">
                  URL webhook : {window.location.origin}/api/webhooks/pawapay/{settings.pawapay_callback_secret}
                </div>
              )}
            </div>
            <Button
              onClick={() => save({
                pawapay_enabled: settings.pawapay_enabled,
                pawapay_environment: settings.pawapay_environment,
                pawapay_country: settings.pawapay_country,
                pawapay_callback_secret: settings.pawapay_callback_secret,
                ...(pawapaySandboxNewToken ? { pawapay_api_token_sandbox: pawapaySandboxNewToken } : {}),
                ...(pawapayProductionNewToken ? { pawapay_api_token_production: pawapayProductionNewToken } : {}),
              })}
              disabled={saving}
              className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
              data-testid="save-pawapay-btn"
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
