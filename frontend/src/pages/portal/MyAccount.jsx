import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Save, KeyRound, Upload, ExternalLink, FileText, Loader2, Sparkles } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/contexts/AuthContext";

// Accessible à TOUT utilisateur connecté, staff comme client — contrairement
// au reste de l'admin, réservé au cabinet (voir PortalLayout.jsx).
export default function MyAccount() {
  const { user, isClient, refresh } = useAuth();
  const [form, setForm] = useState({
    full_name: "", phone: "", whatsapp_number: "", can_receive_notifications: true,
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [pwd, setPwd] = useState({ current_password: "", new_password: "", confirm: "" });
  const [changingPwd, setChangingPwd] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/me/account");
      setForm({
        full_name: data.full_name || "",
        phone: data.phone || "",
        whatsapp_number: data.whatsapp_number || "",
        can_receive_notifications: data.can_receive_notifications !== false,
      });
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    if (!form.full_name.trim()) { toast.error("Le nom complet est requis"); return; }
    setSaving(true);
    try {
      await apiClient.patch("/me/account", form);
      toast.success("Compte mis à jour");
      await refresh();
    } catch (err) {
      toast.error(extractError(err));
    } finally { setSaving(false); }
  };

  const changePassword = async () => {
    if (!pwd.current_password || !pwd.new_password) { toast.error("Mot de passe actuel et nouveau requis"); return; }
    if (pwd.new_password.length < 8) { toast.error("8 caractères minimum"); return; }
    if (pwd.new_password !== pwd.confirm) { toast.error("La confirmation ne correspond pas"); return; }
    setChangingPwd(true);
    try {
      await apiClient.post("/me/account/change-password", {
        current_password: pwd.current_password, new_password: pwd.new_password,
      });
      toast.success("Mot de passe changé");
      setPwd({ current_password: "", new_password: "", confirm: "" });
    } catch (err) {
      toast.error(extractError(err, "Mot de passe actuel incorrect"));
    } finally { setChangingPwd(false); }
  };

  return (
    <div className="space-y-6" data-testid="my-account-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Mon espace</div>
        <h1 className="font-display text-3xl md:text-4xl text-foreground">Mon compte</h1>
        <p className="text-muted-foreground mt-1">Coordonnées, notifications et sécurité de votre compte.</p>
      </div>

      <div className="albarka-card p-6 space-y-4 max-w-2xl">
        <div className="font-semibold">Informations du compte</div>
        {loading ? (
          <div className="text-sm text-muted-foreground">Chargement…</div>
        ) : (
          <>
            <div>
              <Label>Email</Label>
              <Input value={user?.email || ""} readOnly className="bg-muted" data-testid="my-account-email" />
            </div>
            <div>
              <Label>Nom complet</Label>
              <Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} data-testid="my-account-name" />
            </div>
            <div>
              <Label>Téléphone</Label>
              <Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="my-account-phone" />
            </div>
            <div>
              <Label>Numéro WhatsApp</Label>
              <Input
                value={form.whatsapp_number}
                onChange={(e) => setForm({ ...form, whatsapp_number: e.target.value })}
                placeholder="Laisser vide si identique au téléphone"
                data-testid="my-account-whatsapp"
              />
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer pt-1">
              <Switch
                checked={form.can_receive_notifications}
                onCheckedChange={(v) => setForm({ ...form, can_receive_notifications: v })}
                data-testid="my-account-notif-switch"
              />
              <span>Recevoir les notifications (rappels, rapports…)</span>
            </label>
            <Button onClick={save} disabled={saving} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="my-account-save-btn">
              <Save className="w-4 h-4 mr-2" />
              Enregistrer
            </Button>
          </>
        )}
      </div>

      <div className="albarka-card p-6 space-y-4 max-w-2xl">
        <div className="font-semibold flex items-center gap-2"><KeyRound className="w-4 h-4" />Changer le mot de passe</div>
        <div>
          <Label>Mot de passe actuel</Label>
          <Input type="password" value={pwd.current_password} onChange={(e) => setPwd({ ...pwd, current_password: e.target.value })} data-testid="my-account-current-password" />
        </div>
        <div>
          <Label>Nouveau mot de passe</Label>
          <Input type="password" value={pwd.new_password} onChange={(e) => setPwd({ ...pwd, new_password: e.target.value })} data-testid="my-account-new-password" />
        </div>
        <div>
          <Label>Confirmer le nouveau mot de passe</Label>
          <Input type="password" value={pwd.confirm} onChange={(e) => setPwd({ ...pwd, confirm: e.target.value })} data-testid="my-account-confirm-password" />
        </div>
        <Button onClick={changePassword} disabled={changingPwd} variant="outline" data-testid="my-account-change-password-btn">
          {changingPwd ? "Changement…" : "Changer le mot de passe"}
        </Button>
      </div>

      {isClient && <KycSection />}
    </div>
  );
}

const KYC_DOC_TYPES = [
  { key: "id_photo", label: "Photo (portrait)", accept: "image/*" },
  { key: "id_card", label: "Pièce d'identité (recto/verso)", accept: "image/*,application/pdf" },
  { key: "letterhead", label: "Papier à en-tête / registre du commerce", accept: "image/*,application/pdf" },
];

const KYC_FIELD_LABELS = {
  business_name: "Raison sociale", ifu: "IFU", rccm: "RCCM", address: "Adresse",
};

// Fiche KYC — réservée aux comptes clients (voir albarka_myaccount.py côté
// backend). Les champs texte reconnus dans id_card/letterhead sont
// préremplis automatiquement par l'IA (jamais par-dessus une valeur déjà
// saisie manuellement) — voir le badge "Prérempli par l'IA" sur ces champs.
function KycSection() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingKey, setUploadingKey] = useState(null);
  const [form, setForm] = useState({ business_name: "", ifu: "", rccm: "", address: "", bank_details: "" });
  const [urls, setUrls] = useState({ id_photo_url: null, id_card_url: null, letterhead_url: null });
  const [aiPrefilled, setAiPrefilled] = useState([]);
  const fileRefs = useRef({});

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/me/kyc");
      setForm({
        business_name: data.business_name || "", ifu: data.ifu || "", rccm: data.rccm || "",
        address: data.address || "", bank_details: data.bank_details || "",
      });
      setUrls({
        id_photo_url: data.id_photo_url || null, id_card_url: data.id_card_url || null,
        letterhead_url: data.letterhead_url || null,
      });
      setAiPrefilled(data.ai_prefilled_fields || []);
    } catch (err) {
      toast.error(extractError(err, "Erreur chargement KYC"));
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      await apiClient.put("/me/kyc", form);
      toast.success("Fiche KYC enregistrée");
    } catch (err) {
      toast.error(extractError(err));
    } finally { setSaving(false); }
  };

  const onFileSelected = async (docType, e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (f.size > 8 * 1024 * 1024) {
      toast.error(`Fichier trop volumineux (max 8 Mo, actuel : ${(f.size / 1024 / 1024).toFixed(1)} Mo)`);
      return;
    }
    setUploadingKey(docType);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const { data } = await apiClient.post(`/me/kyc/upload/${docType}`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUrls((u) => ({ ...u, [`${docType}_url`]: data.url || null }));
      if (data.ai_prefilled_fields?.length) {
        toast.success(`Champs préremplis par l'IA : ${data.ai_prefilled_fields.map((f2) => KYC_FIELD_LABELS[f2] || f2).join(", ")}`);
        await load();
      } else {
        toast.success("Document enregistré");
      }
    } catch (err) {
      toast.error(extractError(err, "Erreur upload"));
    } finally { setUploadingKey(null); }
  };

  return (
    <div className="albarka-card p-6 space-y-4 max-w-2xl" data-testid="my-account-kyc-section">
      <div className="font-semibold">Fiche KYC (données fiscales &amp; documents)</div>
      <p className="text-xs text-muted-foreground -mt-2">
        Téléversez votre registre du commerce ou papier à en-tête : nos IA analysent le document et
        préremplissent automatiquement les champs reconnus ci-dessous.
      </p>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" />Chargement…</div>
      ) : (
        <>
          <div className="grid sm:grid-cols-2 gap-3">
            {["business_name", "ifu", "rccm"].map((key) => (
              <div key={key}>
                <Label className="flex items-center gap-1.5">
                  {KYC_FIELD_LABELS[key]}
                  {aiPrefilled.includes(key) && (
                    <span className="inline-flex items-center gap-0.5 text-[10px] text-indigo-600" title="Prérempli automatiquement par l'IA">
                      <Sparkles className="w-3 h-3" />IA
                    </span>
                  )}
                </Label>
                <Input
                  value={form[key]}
                  onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                  data-testid={`kyc-${key.replace("_", "-")}`}
                />
              </div>
            ))}
            <div className="sm:col-span-2">
              <Label className="flex items-center gap-1.5">
                Adresse
                {aiPrefilled.includes("address") && (
                  <span className="inline-flex items-center gap-0.5 text-[10px] text-indigo-600" title="Prérempli automatiquement par l'IA">
                    <Sparkles className="w-3 h-3" />IA
                  </span>
                )}
              </Label>
              <Input value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} data-testid="kyc-address" />
            </div>
            <div className="sm:col-span-2">
              <Label>Coordonnées bancaires</Label>
              <Textarea rows={2} value={form.bank_details} onChange={(e) => setForm({ ...form, bank_details: e.target.value })} data-testid="kyc-bank" />
            </div>
          </div>
          <Button onClick={save} disabled={saving} variant="outline" data-testid="kyc-save-btn">
            <Save className="w-4 h-4 mr-2" />
            Enregistrer les données
          </Button>

          <div className="pt-3 border-t space-y-2">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Documents (max 8 Mo, PDF ou image)
            </div>
            {KYC_DOC_TYPES.map((dt) => {
              const url = urls[`${dt.key}_url`];
              const busy = uploadingKey === dt.key;
              return (
                <div key={dt.key} className="flex items-center gap-2 rounded-lg bg-white ring-1 ring-border p-2">
                  <FileText className="w-4 h-4 text-[#0F6B4A] shrink-0" />
                  <span className="text-sm flex-1 min-w-0 truncate">{dt.label}</span>
                  {url && (
                    <a href={url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#0F6B4A] hover:underline flex items-center gap-0.5" data-testid={`kyc-view-${dt.key}`}>
                      Voir <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                  <input
                    ref={(el) => { fileRefs.current[dt.key] = el; }}
                    type="file" accept={dt.accept} onChange={(e) => onFileSelected(dt.key, e)}
                    className="hidden" data-testid={`kyc-file-${dt.key}`}
                  />
                  <Button
                    type="button" size="sm" variant="outline"
                    onClick={() => fileRefs.current[dt.key]?.click()} disabled={busy}
                    data-testid={`kyc-upload-${dt.key}`}
                  >
                    {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Upload className="w-3 h-3" />}
                    <span className="ml-1">{busy ? "Envoi…" : (url ? "Remplacer" : "Choisir")}</span>
                  </Button>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
