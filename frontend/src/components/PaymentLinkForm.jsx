import React, { useState } from "react";
import { toast } from "sonner";
import { Copy, ExternalLink } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import EntitySelect from "@/components/EntitySelect";

/**
 * Corps partagé du formulaire "Générer un lien de paiement" (POST
 * /payments/pawapay/link) — utilisé à la fois par la page Paiements
 * (AdminPayments.jsx) et par la bulle flottante (PaymentBubble.jsx), pour
 * ne pas dupliquer la logique entre les deux points d'entrée.
 */
export default function PaymentLinkForm({ onCreated, compact = false }) {
  const [tenantId, setTenantId] = useState("");
  const [amount, setAmount] = useState("");
  const [msisdn, setMsisdn] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  const submit = async () => {
    if (!tenantId || !amount) { toast.error("Client et montant requis"); return; }
    setSubmitting(true);
    try {
      const { data } = await apiClient.post("/payments/pawapay/link", {
        tenant_id: tenantId, amount: Number(amount),
        msisdn: msisdn.trim() || undefined, reason: reason.trim() || undefined,
      });
      setResult(data);
      onCreated?.(data);
    } catch (err) {
      toast.error(extractError(err, "Échec de la génération du lien"));
    } finally { setSubmitting(false); }
  };

  const copyLink = () => {
    navigator.clipboard.writeText(result.redirect_url);
    toast.success("Lien copié");
  };

  const reset = () => {
    setTenantId(""); setAmount(""); setMsisdn(""); setReason(""); setResult(null);
  };

  if (result) {
    return (
      <div className="space-y-3" data-testid="payment-link-result">
        <div className="text-sm text-muted-foreground">Lien de paiement généré :</div>
        <div className="p-2 bg-muted rounded text-xs break-all font-mono" data-testid="payment-link-value">{result.redirect_url}</div>
        <div className="flex gap-2 flex-wrap">
          <Button variant="outline" size="sm" onClick={copyLink} data-testid="payment-copy-btn">
            <Copy className="w-4 h-4 mr-1" />Copier
          </Button>
          <a href={result.redirect_url} target="_blank" rel="noopener noreferrer">
            <Button variant="outline" size="sm" data-testid="payment-open-btn">
              <ExternalLink className="w-4 h-4 mr-1" />Ouvrir
            </Button>
          </a>
        </div>
        <Button variant="ghost" size="sm" onClick={reset} data-testid="payment-new-btn">
          Créer un autre lien
        </Button>
      </div>
    );
  }

  return (
    <div className={compact ? "space-y-2" : "space-y-3"}>
      <div>
        <Label className="text-xs">Client</Label>
        <EntitySelect value={tenantId} onChange={setTenantId} testId="payment-tenant-input" />
      </div>
      <div>
        <Label className="text-xs">Montant (XOF)</Label>
        <Input type="number" min="1" value={amount} onChange={(e) => setAmount(e.target.value)} data-testid="payment-amount-input" />
      </div>
      <div>
        <Label className="text-xs">Téléphone mobile money (optionnel)</Label>
        <Input
          value={msisdn} onChange={(e) => setMsisdn(e.target.value)}
          placeholder="Laisser vide : le client le saisit lui-même" data-testid="payment-msisdn-input"
        />
      </div>
      <div>
        <Label className="text-xs">Motif (optionnel)</Label>
        <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={50} data-testid="payment-reason-input" />
      </div>
      <Button
        onClick={submit} disabled={submitting}
        className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white w-full" data-testid="payment-submit-btn"
      >
        {submitting ? "Génération…" : "Générer le lien de paiement"}
      </Button>
    </div>
  );
}
