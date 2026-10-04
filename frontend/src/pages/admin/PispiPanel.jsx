/*
  PispiPanel — « Encaissement PI-SPI » (lot 14), réglage GLOBAL du cabinet.
  Affiché dans Paramètres → Paiements (Superviseur) et dans Caisse → PI-SPI
  (Direction).

  PI-SPI = paiement instantané de la BCEAO. Le QR code est fourni par la
  banque du cabinet : on l'imprime tel quel sur les factures (jamais inventé).
  Deux façons de le donner :
    - le TEXTE décodé du QR (le portail génère l'image à partir de ce texte,
      sans aucune modification) ;
    - ou l'IMAGE du QR (PNG/JPG, 1 Mo maximum), stockée dans R2.
  Quand l'encaissement est actif, chaque facture non soldée porte le bloc
  « Payer par PI-SPI » (QR, adresse de paiement, reste dû, référence = n° de
  facture, consigne) ; les proformas portent « Modalités de paiement » sans
  montant.
  Écriture : Superviseur, Direction. API : /admin/pispi, /admin/pispi/qr
*/
import React, { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Save, Upload, Trash2, QrCode } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";

// Taille maximale de l'image du QR (1 Mo, contrôlée aussi par le serveur)
const QR_MAX = 1024 * 1024;

export default function PispiPanel() {
  const [p, setP] = useState(null);              // paramètres affichés
  const [saving, setSaving] = useState(false);
  const [qrSrc, setQrSrc] = useState(null);      // aperçu du QR (blob local)
  const [stamp, setStamp] = useState(0);         // force le rechargement de l'aperçu
  const fileRef = useRef(null);

  // Chargement des paramètres
  useEffect(() => {
    apiClient.get("/admin/pispi").then(({ data }) => setP(data)).catch((e) => toast.error(extractError(e)));
  }, []);

  // Aperçu du QR tel qu'il sera imprimé (rechargé après chaque modification)
  useEffect(() => {
    let url;
    if (!p?.qr_present) { setQrSrc(null); return undefined; }
    apiClient.get("/admin/pispi/qr", { responseType: "blob" })
      .then((r) => { url = URL.createObjectURL(r.data); setQrSrc(url); })
      .catch(() => setQrSrc(null));
    return () => url && URL.revokeObjectURL(url);
  }, [p?.qr_present, stamp]);

  if (!p) return <div className="text-sm text-muted-foreground">Chargement…</div>;

  // Enregistrement des champs texte (toast « Patientez… » pendant l'appel)
  const save = async () => {
    setSaving(true);
    const wait = toast.loading("Patientez…");
    try {
      const { data } = await apiClient.put("/admin/pispi", {
        actif: !!p.actif, banque: p.banque, banque_autre: p.banque_autre || "", titulaire: p.titulaire || "",
        adresse_paiement: p.adresse_paiement || "", qr_contenu: p.qr_contenu || "", consigne: p.consigne || "",
      });
      setP(data); setStamp((s) => s + 1);
      toast.success("Encaissement PI-SPI enregistré");
    } catch (e) {
      toast.error(extractError(e));
    } finally { toast.dismiss(wait); setSaving(false); }
  };

  // Téléversement de l'image du QR fournie par la banque
  const upload = async (file) => {
    if (!file) return;
    if (file.size > QR_MAX) { toast.error("Image trop volumineuse (1 Mo maximum)"); return; }
    const fd = new FormData();
    fd.append("file", file);
    const wait = toast.loading("Patientez… envoi de l'image");
    try {
      const { data } = await apiClient.post("/admin/pispi/qr", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setP((cur) => ({ ...data, ...pickTexts(cur) })); setStamp((s) => s + 1);
      toast.success("Image du QR enregistrée");
    } catch (e) {
      toast.error(extractError(e));
    } finally { toast.dismiss(wait); if (fileRef.current) fileRef.current.value = ""; }
  };

  // Suppression de l'image (le texte décodé, s'il existe, reste utilisé)
  const removeImage = async () => {
    try {
      const { data } = await apiClient.delete("/admin/pispi/qr");
      setP((cur) => ({ ...data, ...pickTexts(cur) })); setStamp((s) => s + 1);
    } catch (e) { toast.error(extractError(e)); }
  };

  // Champs en cours de saisie conservés après un envoi d'image
  const pickTexts = (cur) => ({
    actif: cur.actif, banque: cur.banque, banque_autre: cur.banque_autre, titulaire: cur.titulaire,
    adresse_paiement: cur.adresse_paiement, qr_contenu: cur.qr_contenu, consigne: cur.consigne,
  });

  const set = (k) => (e) => setP({ ...p, [k]: e.target.value });

  return (
    <div className="albarka-card p-6 space-y-4 max-w-2xl" data-testid="pispi-panel">
      {/* En-tête + interrupteur « actif » */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="font-semibold flex items-center gap-2"><QrCode className="w-4 h-4" /> Encaissement PI-SPI</div>
          <div className="text-sm text-muted-foreground">
            Paiement instantané BCEAO. Le bloc « Payer par PI-SPI » (QR de votre banque, adresse de paiement,
            reste dû, référence = n° de facture) est imprimé sur les factures non soldées ; les proformas
            indiquent seulement les modalités de paiement.
          </div>
        </div>
        <Switch checked={!!p.actif} onCheckedChange={(v) => setP({ ...p, actif: v })} data-testid="pispi-actif-switch" />
      </div>

      {/* Banque et titulaire */}
      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <Label>Banque</Label>
          <select className="w-full h-9 text-sm rounded-md border border-input bg-background px-3"
            value={p.banque || "uba"} onChange={set("banque")} data-testid="pispi-banque-select">
            {Object.entries(p.banques || {}).map(([code, lib]) => <option key={code} value={code}>{lib}</option>)}
          </select>
        </div>
        {p.banque === "autre" && (
          <div><Label>Nom de la banque</Label><Input value={p.banque_autre || ""} onChange={set("banque_autre")} data-testid="pispi-banque-autre" /></div>
        )}
        <div className="sm:col-span-2"><Label>Titulaire (nom affiché)</Label>
          <Input value={p.titulaire || ""} onChange={set("titulaire")} placeholder="Cabinet ALBARKA" data-testid="pispi-titulaire" /></div>
        <div className="sm:col-span-2"><Label>Adresse de paiement PI-SPI (fournie par la banque)</Label>
          <Input value={p.adresse_paiement || ""} onChange={set("adresse_paiement")} data-testid="pispi-adresse" /></div>
      </div>

      {/* QR : texte décodé ou image */}
      <div className="grid sm:grid-cols-[1fr_auto] gap-4 items-start">
        <div className="space-y-2">
          <Label>Texte décodé du QR fourni par la banque (facultatif)</Label>
          <Textarea rows={3} value={p.qr_contenu || ""} onChange={set("qr_contenu")} className="font-mono text-xs"
            placeholder="Collez ici le contenu exact du QR (il sera imprimé sans modification)" data-testid="pispi-qr-texte" />
          <div className="text-xs text-muted-foreground">
            Ou bien téléversez l'image du QR (PNG/JPG, 1 Mo max) — l'image est alors imprimée telle quelle.
          </div>
          <div className="flex gap-2">
            <input ref={fileRef} type="file" accept="image/png,image/jpeg" className="hidden"
              onChange={(e) => upload(e.target.files?.[0])} data-testid="pispi-qr-file" />
            <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
              <Upload className="w-4 h-4 mr-1.5" /> Image du QR
            </Button>
            {p.qr_image_presente && (
              <Button type="button" variant="outline" size="sm" onClick={removeImage} data-testid="pispi-qr-remove">
                <Trash2 className="w-4 h-4 mr-1.5" /> Retirer l'image
              </Button>
            )}
          </div>
        </div>
        {/* Aperçu du QR imprimé */}
        <div className="w-32 h-32 rounded border border-slate-200 bg-white flex items-center justify-center">
          {qrSrc ? <img src={qrSrc} alt="QR PI-SPI" className="w-full h-full object-contain" data-testid="pispi-qr-preview" />
            : <span className="text-[11px] text-muted-foreground text-center px-2">Aucun QR enregistré</span>}
        </div>
      </div>

      {/* Consigne imprimée sous le QR */}
      <div>
        <Label>Consigne imprimée sur la facture</Label>
        <Textarea rows={2} value={p.consigne || ""} onChange={set("consigne")} placeholder={p.consigne_defaut} data-testid="pispi-consigne" />
      </div>

      <div className="text-xs text-muted-foreground">
        Encaissement : le Caissier saisit le règlement en mode « PI-SPI » avec la référence bancaire de la
        transaction. Aucune API bancaire n'est encore branchée (connecteur manuel).
      </div>

      <Button onClick={save} disabled={saving} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="pispi-save-btn">
        <Save className="w-4 h-4 mr-2" /> Enregistrer
      </Button>
    </div>
  );
}
