/*
  « Factures & documents » (espace client) — tout ce que le cabinet a mis à
  disposition du client connecté : factures, proformas, reçus (Caisse du
  portail ou faits ailleurs), rapports, attestations, courriers…
  Rien d'autre n'est visible : le serveur ne renvoie que les documents de ce
  client, rendus visibles par le cabinet (API /me/space).
*/
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { FolderOpen, Download, Eye, Loader2 } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import PushOptIn from "@/components/PushOptIn";

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "");
const fmtAmount = (n) => `${Math.round(Number(n || 0)).toLocaleString("fr-FR")} FCFA`;
// Statut de paiement affiché pour une facture de la Caisse
const STATUS = { paid: ["Payée", "bg-emerald-100 text-emerald-800"], partial: ["Partiellement payée", "bg-amber-100 text-amber-800"],
  unpaid: ["À payer", "bg-rose-100 text-rose-800"] };

export default function CabinetDocuments() {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState("all");

  const load = () => apiClient.get("/me/space").then(({ data: d }) => setData(d)).catch((e) => { toast.error(extractError(e)); setData({ items: [] }); });
  useEffect(() => { load(); }, []);

  // Onglets : « Tout » + une catégorie par type de document effectivement présent
  const tabs = useMemo(() => {
    const counts = {};
    (data?.items || []).forEach((i) => { counts[i.category] = (counts[i.category] || 0) + 1; });
    return [{ key: "all", label: "Tout", n: data?.items?.length || 0 },
      ...(data?.categories || []).filter((c) => counts[c.key]).map((c) => ({ key: c.key, label: c.label, n: counts[c.key] }))];
  }, [data]);
  const shown = (data?.items || []).filter((i) => tab === "all" || i.category === tab);
  const newCount = (data?.items || []).filter((i) => i.is_new).length;

  // Ouvre (ou télécharge) le fichier ; la première ouverture est notée côté cabinet
  const open = async (it, download = false) => {
    try {
      const res = await apiClient.get(`/me/space/${it.source}/${it.id}/file`, { params: download ? { download: true } : undefined, responseType: "blob" });
      const url = window.URL.createObjectURL(res.data);
      if (download) {
        const a = document.createElement("a");
        a.href = url; a.download = it.filename || "document"; document.body.appendChild(a); a.click(); a.remove();
      } else {
        window.open(url, "_blank");
      }
      if (it.is_new) load();
    } catch (err) { toast.error(extractError(err, "Ouverture impossible")); }
  };

  return (
    <div className="space-y-5" data-testid="cabinet-documents-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Mon espace</div>
        <h1 className="font-display text-3xl">Factures & documents</h1>
        <p className="text-muted-foreground mt-1">
          {data === null ? "" : newCount ? `${newCount} nouveau(x) document(s) du cabinet.` : "Les documents que le cabinet a mis à votre disposition."}
        </p>
      </div>
      {/* Notifications push sur cet appareil (téléphone, ordinateur) */}
      <PushOptIn />
      {tabs.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {tabs.map((t) => (
            <button key={t.key} type="button" onClick={() => setTab(t.key)} data-testid={`cd-tab-${t.key}`}
              className={`px-3 py-1.5 rounded-full text-sm border ${tab === t.key ? "bg-[#0F6B4A] text-white border-[#0F6B4A]" : "bg-white text-slate-700"}`}>
              {t.label} <span className="opacity-70">({t.n})</span>
            </button>
          ))}
        </div>
      )}
      {data === null ? (
        <p className="text-sm text-muted-foreground inline-flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Chargement…</p>
      ) : shown.length === 0 ? (
        <div className="albarka-card p-10 text-center text-muted-foreground"><FolderOpen className="w-10 h-10 mx-auto mb-2 opacity-40" /> Aucun document pour l'instant.</div>
      ) : (
        <div className="space-y-2">
          {shown.map((it) => (
            <div key={`${it.source}-${it.id}`} className="albarka-card p-4 flex flex-wrap items-center gap-3" data-testid={`cd-item-${it.id}`}>
              <div className="flex-1 min-w-[220px]">
                <div className="font-medium flex items-center gap-2">
                  {it.title}
                  {it.is_new && <span className="albarka-chip text-[10px] bg-[#E5A24B]/20 text-[#8a5a14]">Nouveau</span>}
                </div>
                <div className="text-xs text-muted-foreground">
                  {it.category_label}{it.reference ? ` · ${it.reference}` : ""}{it.date ? ` · ${fmtDate(it.date)}` : ""}{it.amount ? ` · ${fmtAmount(it.amount)}` : ""}
                </div>
              </div>
              {/* Facture de la Caisse : statut et reste à payer */}
              {it.category === "facture" && STATUS[it.status] && (
                <span className={`albarka-chip text-xs ${STATUS[it.status][1]}`}>
                  {STATUS[it.status][0]}{it.status !== "paid" && it.remaining ? ` — reste ${fmtAmount(it.remaining)}` : ""}
                </span>
              )}
              <Button size="sm" variant="outline" onClick={() => open(it)} data-testid={`cd-open-${it.id}`}><Eye className="w-4 h-4 mr-1" /> Ouvrir</Button>
              <Button size="sm" variant="ghost" onClick={() => open(it, true)} title="Télécharger"><Download className="w-4 h-4" /></Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
