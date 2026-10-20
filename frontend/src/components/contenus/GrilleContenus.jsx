/*
  Grille de vignettes façon « skool » (lot 54) — partagée par « Infos » et « Formations ».
  Chaque carte : image d'aperçu, titre, thème, date, format, et pastille Gratuit / prix / Verrouillé.
  Au clic : fenêtre de lecture (vidéo intégrée, audio, PDF ou lien). Une formation payante verrouillée
  propose « Acheter » (paiement mobile money PawaPay) via `onAcheter`.
*/
import React, { useState } from "react";
import { toast } from "sonner";
import { Play, Headphones, FileText, Link2, Lock, Loader2 } from "lucide-react";
import { API, apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export const THEMES = { comptabilite: "Comptabilité", fiscalite: "Fiscalité", rh: "Ressources humaines", cnss: "CNSS", autre: "Autre" };
const ICONES = { video: Play, audio: Headphones, pdf: FileText, lien: Link2 };
const fmtDate = (d) => (d ? new Date(d).toLocaleDateString("fr-FR") : "");
const fmtPrix = (n) => `${Math.round(Number(n || 0)).toLocaleString("fr-FR")} FCFA`;

// Image d'aperçu : vignette téléversée, sinon aperçu YouTube, sinon fond uni avec l'icône du format
function Apercu({ c }) {
  const Icone = ICONES[c.format] || FileText;
  const src = c.a_vignette ? (c.vignette_externe || `${API}/contenus/${c.id}/vignette`) : null;
  return (
    <div className="aspect-video bg-gradient-to-br from-[#0B1912] to-[#0F6B4A] flex items-center justify-center overflow-hidden relative">
      {src ? <img src={src} alt="" className="w-full h-full object-cover" loading="lazy" /> : <Icone className="w-10 h-10 text-white/70" />}
      {src && <span className="absolute inset-0 flex items-center justify-center"><span className="rounded-full bg-black/50 p-2"><Icone className="w-5 h-5 text-white" /></span></span>}
      {!c.acces && <span className="absolute inset-0 bg-black/45 flex items-center justify-center"><Lock className="w-7 h-7 text-white" /></span>}
    </div>
  );
}

export default function GrilleContenus({ contenus, onAcheter, vide = "Rien à afficher pour le moment." }) {
  const [ouvert, setOuvert] = useState(null);
  const [media, setMedia] = useState(null);             // URL locale du PDF / de l'audio chargé
  const [attente, setAttente] = useState(false);

  const ouvrir = async (c) => {
    setOuvert(c); setMedia(null);
    if (c.acces && c.a_fichier) {
      try {
        const r = await apiClient.get(`/contenus/${c.id}/fichier`, { responseType: "blob" });
        setMedia(URL.createObjectURL(r.data));
      } catch (e) { toast.error(extractError(e, "Ouverture impossible")); }
    }
  };
  const acheter = async (c) => {
    setAttente(true);
    try { await onAcheter(c); } catch (e) { toast.error(extractError(e, "Paiement impossible")); } finally { setAttente(false); }
  };

  if (!contenus.length) return <div className="text-sm text-muted-foreground">{vide}</div>;
  return (
    <>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="grille-contenus">
        {contenus.map((c) => (
          <button key={c.id} type="button" onClick={() => ouvrir(c)} data-testid="carte-contenu"
            className="text-left rounded-xl border bg-white overflow-hidden hover:shadow-md transition-shadow focus:outline-none focus:ring-2 focus:ring-[#0F6B4A]">
            <Apercu c={c} />
            <div className="p-3 space-y-1">
              <div className="font-medium leading-snug">{c.titre}</div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>{THEMES[c.theme] || c.theme}</span><span>·</span><span>{fmtDate(c.publie_le)}</span>
                {c.type === "formation" && (
                  <span className={`ml-auto px-2 py-0.5 rounded-full ${c.gratuit ? "bg-emerald-100 text-emerald-800" : c.acces ? "bg-sky-100 text-sky-800" : "bg-amber-100 text-amber-800"}`}>
                    {c.gratuit ? "Gratuit" : c.acces ? "Acheté" : fmtPrix(c.prix)}
                  </span>
                )}
                {c.publie === false && <span className="ml-auto px-2 py-0.5 rounded-full bg-slate-200">Brouillon</span>}
              </div>
            </div>
          </button>
        ))}
      </div>

      <Dialog open={!!ouvert} onOpenChange={(o) => { if (!o) { setOuvert(null); setMedia(null); } }}>
        <DialogContent className="max-w-xl">
          {ouvert && (<>
            <DialogHeader><DialogTitle>{ouvert.titre}</DialogTitle></DialogHeader>
            <div className="space-y-3 text-sm">
              {ouvert.description && <p className="whitespace-pre-wrap text-slate-700">{ouvert.description}</p>}
              {!ouvert.acces ? (
                <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 space-y-2">
                  <div>Formation payante : <b>{fmtPrix(ouvert.prix)}</b>. Règlement par mobile money (Orange, Moov, Telecel).</div>
                  <Button disabled={attente} onClick={() => acheter(ouvert)} className="bg-[#0F6B4A] hover:bg-[#0B5A3E]" data-testid="btn-acheter">
                    {attente && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}Acheter cette formation
                  </Button>
                </div>
              ) : ouvert.embed_url ? (
                <div className="aspect-video"><iframe title={ouvert.titre} src={ouvert.embed_url} className="w-full h-full rounded-lg" allowFullScreen
                  allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" /></div>
              ) : ouvert.format === "audio" ? (media ? <audio controls src={media} className="w-full" /> : <div className="text-muted-foreground">Chargement…</div>)
              : ouvert.format === "pdf" ? (media ? <Button onClick={() => window.open(media, "_blank")}><FileText className="w-4 h-4 mr-2" />Ouvrir le document</Button> : <div className="text-muted-foreground">Chargement…</div>)
              : ouvert.url ? <a href={ouvert.url} target="_blank" rel="noopener noreferrer" className="text-[#0F6B4A] underline">Ouvrir le lien</a> : null}
            </div>
          </>)}
        </DialogContent>
      </Dialog>
    </>
  );
}
