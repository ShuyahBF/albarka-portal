/*
  « Outils Numériques » (lot 9) — page commune aux clients (/portal) et au
  personnel (/admin) : grille des outils visibles destinés à l'utilisateur
  connecté. Un clic sur l'image (ou la carte) lance le téléchargement.
*/
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Download, HardDriveDownload, Loader2, SlidersHorizontal } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { downloadTool } from "@/lib/outils";
import ToolVisual from "@/components/outils/ToolVisual";

export default function OutilsNumeriques({ admin = false }) {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(null);

  // Le serveur ne renvoie que les outils visibles destinés à ce public
  useEffect(() => {
    apiClient.get("/outils-numeriques")
      .then(({ data: d }) => setData(d))
      .catch((e) => { toast.error(extractError(e)); setData({ items: [] }); });
  }, []);

  const onDownload = async (tool) => {
    if (busy) return;
    setBusy(tool.id);
    try { await downloadTool(tool); } finally { setTimeout(() => setBusy(null), 800); }
  };

  const items = data?.items || [];
  return (
    <div className="space-y-6" data-testid="outils-numeriques-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">{admin ? "Cabinet" : "Mon espace"}</div>
          <h1 className="font-display text-3xl">Outils Numériques</h1>
          <p className="text-muted-foreground mt-1">Logiciels, documents et applications mis à disposition par le cabinet. Cliquez sur une image pour télécharger.</p>
        </div>
        {/* Raccourci vers la gestion, pour l'administrateur du portail */}
        {admin && data?.is_super_admin && (
          <Link to="/admin/outils-numeriques/gestion" className="inline-flex items-center gap-2 text-sm text-[#0F6B4A] hover:underline" data-testid="outils-manage-link">
            <SlidersHorizontal className="w-4 h-4" /> Gérer les outils
          </Link>
        )}
      </div>

      {data === null && (
        <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /> Chargement…</div>
      )}
      {data !== null && items.length === 0 && (
        <div className="albarka-card p-10 text-center text-muted-foreground" data-testid="outils-empty">
          <HardDriveDownload className="w-10 h-10 mx-auto mb-3 opacity-40" />
          Aucun outil disponible pour le moment.
        </div>
      )}

      {/* Grille responsive : 2 colonnes sur téléphone, jusqu'à 6 sur grand écran */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-4">
        {items.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => onDownload(t)}
            disabled={busy === t.id}
            title={`Télécharger ${t.caption}`}
            className="albarka-card p-4 flex flex-col items-center text-center gap-2 hover:shadow-md hover:-translate-y-0.5 transition disabled:opacity-60"
            data-testid={`outil-card-${t.id}`}
          >
            <div className="relative">
              <ToolVisual tool={t} size={96} />
              <span className="absolute -bottom-1 -right-1 w-7 h-7 rounded-full bg-[#0F6B4A] text-white flex items-center justify-center shadow">
                {busy === t.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
              </span>
            </div>
            <div className="font-medium text-sm leading-tight mt-1 break-words w-full">{t.caption}</div>
            <div className="text-[11px] text-muted-foreground">
              {[t.version && `v${t.version.replace(/^v/i, "")}`, t.size_label].filter(Boolean).join(" · ")}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
