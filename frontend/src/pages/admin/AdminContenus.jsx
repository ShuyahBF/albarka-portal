/*
  « Infos & formations » (cabinet, lot 54) — publier une info de la semaine ou une formation :
  titre, thème, format (vidéo en lien YouTube/Vimeo, audio, PDF, lien), vignette, prix (0 = gratuit),
  publication immédiate ou brouillon. Les vidéos restent chez YouTube/Vimeo pour ne pas saturer le stockage.
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Eye, EyeOff } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import GrilleContenus from "@/components/contenus/GrilleContenus";

const VIDE = { titre: "", description: "", theme: "comptabilite", format: "video", url: "", prix: "0", publie_le: "", publie: true };

export default function AdminContenus() {
  const [type, setType] = useState("info");
  const [liste, setListe] = useState(null);
  const [opts, setOpts] = useState({ themes: [], formats: [] });
  const [form, setForm] = useState(null);                 // null = fenêtre fermée
  const [fichier, setFichier] = useState(null);
  const [vignette, setVignette] = useState(null);
  const [envoi, setEnvoi] = useState(false);
  const [selection, setSelection] = useState(null);

  const charger = useCallback(() => apiClient.get("/contenus/admin/tout").then(({ data }) => setListe(data))
    .catch((e) => { toast.error(extractError(e)); setListe([]); }), []);
  useEffect(() => { charger(); apiClient.get("/contenus/options").then(({ data }) => setOpts(data)).catch(() => {}); }, [charger]);

  const maj = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const enregistrer = async (e) => {
    e.preventDefault();
    const fd = new FormData();
    Object.entries({ ...form, type }).forEach(([k, v]) => fd.append(k, String(v)));
    if (fichier) fd.append("fichier", fichier);
    if (vignette) fd.append("vignette", vignette);
    setEnvoi(true);
    try {
      await apiClient.post("/contenus", fd);
      toast.success("Contenu enregistré");
      setForm(null); setFichier(null); setVignette(null); charger();
    } catch (err) { toast.error(extractError(err)); } finally { setEnvoi(false); }
  };
  const basculer = async (c) => { try { await apiClient.patch(`/contenus/${c.id}`, { publie: !c.publie }); charger(); setSelection(null); } catch (e) { toast.error(extractError(e)); } };
  const supprimer = async (c) => { try { await apiClient.delete(`/contenus/${c.id}`); toast.success("Supprimé"); setSelection(null); charger(); } catch (e) { toast.error(extractError(e)); } };

  const affiches = (liste || []).filter((c) => c.type === type);
  const besoinFichier = form && ["pdf", "audio"].includes(form.format);
  return (
    <div className="space-y-5" data-testid="admin-contenus-page">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="font-display text-3xl">Infos & formations</h1>
          <p className="text-muted-foreground mt-1">Contenus affichés dans l'espace client (rubriques « Infos » et « Formations »).</p>
        </div>
        <Button className="ml-auto bg-[#0F6B4A] hover:bg-[#0B5A3E]" onClick={() => setForm({ ...VIDE })} data-testid="btn-nouveau-contenu"><Plus className="w-4 h-4 mr-2" />Nouveau</Button>
      </div>
      <div className="flex gap-2">
        {[["info", "Infos de la semaine"], ["formation", "Formations"]].map(([k, l]) => (
          <button key={k} type="button" onClick={() => setType(k)}
            className={`px-3 py-1.5 rounded-full text-sm border ${type === k ? "bg-[#0F6B4A] text-white border-[#0F6B4A]" : "bg-white text-slate-700"}`}>{l}</button>
        ))}
      </div>
      {liste === null ? <div className="text-sm text-muted-foreground">Chargement…</div> : (
        <>
          <GrilleContenus contenus={affiches} vide="Aucun contenu. Cliquez sur « Nouveau »." />
          <div className="text-xs text-muted-foreground">Astuce : les cartes ci-dessus sont celles que voit le client. Gérez-les ci-dessous.</div>
          <div className="space-y-2">
            {affiches.map((c) => (
              <div key={c.id} className="flex flex-wrap items-center gap-2 rounded-lg border bg-white p-2 text-sm" data-testid="ligne-contenu">
                <span className="font-medium">{c.titre}</span>
                <span className="text-muted-foreground">{c.publie ? "Publié" : "Brouillon"}{c.type === "formation" ? ` · ${c.gratuit ? "gratuit" : `${c.prix} FCFA · ${c.achats} achat(s)`}` : ""}</span>
                <Button variant="ghost" size="sm" className="ml-auto" onClick={() => basculer(c)}>{c.publie ? <><EyeOff className="w-4 h-4 mr-1" />Masquer</> : <><Eye className="w-4 h-4 mr-1" />Publier</>}</Button>
                {selection === c.id
                  ? <Button variant="destructive" size="sm" onClick={() => supprimer(c)}>Confirmer la suppression</Button>
                  : <Button variant="ghost" size="icon" onClick={() => setSelection(c.id)} aria-label="Supprimer"><Trash2 className="w-4 h-4" /></Button>}
              </div>
            ))}
          </div>
        </>
      )}

      <Dialog open={!!form} onOpenChange={(o) => !o && setForm(null)}>
        <DialogContent className="max-w-xl max-h-[85dvh] overflow-y-auto">
          <DialogHeader><DialogTitle>{type === "info" ? "Nouvelle info de la semaine" : "Nouvelle formation"}</DialogTitle></DialogHeader>
          {form && (
            <form onSubmit={enregistrer} className="space-y-3 text-sm">
              <Input placeholder="Titre" value={form.titre} onChange={(e) => maj("titre", e.target.value)} data-testid="ct-titre" />
              <textarea rows={3} placeholder="Description" value={form.description} onChange={(e) => maj("description", e.target.value)}
                className="w-full rounded-md border border-input px-3 py-2" />
              <div className="grid sm:grid-cols-2 gap-3">
                <Select value={form.theme} onValueChange={(v) => maj("theme", v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>{opts.themes.map((t) => <SelectItem key={t.code} value={t.code}>{t.libelle}</SelectItem>)}</SelectContent>
                </Select>
                <Select value={form.format} onValueChange={(v) => maj("format", v)}>
                  <SelectTrigger data-testid="ct-format"><SelectValue /></SelectTrigger>
                  <SelectContent>{opts.formats.map((t) => <SelectItem key={t.code} value={t.code}>{t.libelle}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              {["video", "lien"].includes(form.format) && <Input placeholder="Lien https:// (YouTube non répertorié, Vimeo…)" value={form.url} onChange={(e) => maj("url", e.target.value)} data-testid="ct-url" />}
              {besoinFichier && (
                <label className="block">Fichier {form.format === "pdf" ? "PDF (10 Mo au plus)" : "audio (15 Mo au plus)"}
                  <input type="file" accept={form.format === "pdf" ? ".pdf" : "audio/*"} onChange={(e) => setFichier(e.target.files?.[0] || null)} className="block mt-1" /></label>
              )}
              <label className="block">Vignette (image, 1 Mo au plus — facultative)
                <input type="file" accept="image/*" onChange={(e) => setVignette(e.target.files?.[0] || null)} className="block mt-1" /></label>
              <div className="grid sm:grid-cols-2 gap-3">
                <label>Date de publication<Input type="date" value={form.publie_le} onChange={(e) => maj("publie_le", e.target.value)} /></label>
                {type === "formation" && <label>Prix en FCFA (0 = gratuit)<Input type="number" min="0" value={form.prix} onChange={(e) => maj("prix", e.target.value)} /></label>}
              </div>
              <label className="flex items-center gap-2"><input type="checkbox" checked={form.publie} onChange={(e) => maj("publie", e.target.checked)} />Publier tout de suite (sinon brouillon)</label>
              <Button type="submit" disabled={envoi} className="bg-[#0F6B4A] hover:bg-[#0B5A3E]" data-testid="ct-enregistrer">Enregistrer</Button>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
