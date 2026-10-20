/*
  « Infos & formations » (cabinet, lot 54) — publier une info de la semaine ou une formation :
  titre, thème, format (vidéo en lien YouTube/Vimeo, audio, PDF, lien), vignette, prix (0 = gratuit),
  publication immédiate ou brouillon. Les vidéos restent chez YouTube/Vimeo pour ne pas saturer le stockage.
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Trash2, Eye, EyeOff, ListVideo, KeyRound, Send } from "lucide-react";
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
  const [reglages, setReglages] = useState({ diffusion_wa: true, modele: "message_cabinet" });
  const [leconsDe, setLeconsDe] = useState(null);         // id du contenu dont on gère les leçons
  const [lecon, setLecon] = useState({ titre: "", format: "video", url: "" });
  const [leconFichier, setLeconFichier] = useState(null);
  const [accesDe, setAccesDe] = useState(null);           // id de la formation dont on gère les accès
  const [acces, setAcces] = useState([]);
  const [clients, setClients] = useState([]);
  const [clientChoisi, setClientChoisi] = useState("");

  const charger = useCallback(() => apiClient.get("/contenus/admin/tout").then(({ data }) => setListe(data))
    .catch((e) => { toast.error(extractError(e)); setListe([]); }), []);
  useEffect(() => { charger(); apiClient.get("/contenus/options").then(({ data }) => setOpts(data)).catch(() => {});
    apiClient.get("/contenus/admin/reglages").then(({ data }) => setReglages(data)).catch(() => {}); }, [charger]);

  // Active / coupe la diffusion WhatsApp automatique de l'info de la semaine
  const basculerDiffusion = async (v) => {
    try { const { data } = await apiClient.put("/contenus/admin/reglages", { diffusion_wa: v }); setReglages(data); toast.success(v ? "Diffusion WhatsApp activée" : "Diffusion WhatsApp coupée"); }
    catch (e) { toast.error(extractError(e)); }
  };
  const diffuser = async (c) => { try { await apiClient.post(`/contenus/${c.id}/diffuser`); toast.success("Envoi programmé : il part au prochain passage (entre 7 h et 18 h)"); charger(); } catch (e) { toast.error(extractError(e)); } };

  // Leçons
  const ajouterLecon = async (e) => {
    e.preventDefault();
    const fd = new FormData();
    Object.entries(lecon).forEach(([k, v]) => fd.append(k, v));
    if (leconFichier) fd.append("fichier", leconFichier);
    try { await apiClient.post(`/contenus/${leconsDe}/lecons`, fd); setLecon({ titre: "", format: "video", url: "" }); setLeconFichier(null); charger(); toast.success("Leçon ajoutée"); }
    catch (err) { toast.error(extractError(err)); }
  };
  const retirerLecon = async (lid) => { try { await apiClient.delete(`/contenus/${leconsDe}/lecons/${lid}`); charger(); } catch (e) { toast.error(extractError(e)); } };

  // Accès manuel à une formation payante
  const chargerAcces = (id) => apiClient.get(`/contenus/${id}/acces`).then(({ data }) => setAcces(data)).catch((e) => toast.error(extractError(e)));
  const ouvrirAcces = (id) => {
    setAccesDe(id); setClientChoisi(""); chargerAcces(id);
    if (!clients.length) apiClient.get("/clients").then(({ data }) => setClients(data)).catch(() => {});
  };
  const accorder = async () => {
    if (!clientChoisi) return toast.error("Choisissez un client");
    try { await apiClient.post(`/contenus/${accesDe}/acces`, { tenant_id: clientChoisi }); toast.success("Accès accordé"); setClientChoisi(""); chargerAcces(accesDe); charger(); }
    catch (e) { toast.error(extractError(e)); }
  };
  const retirerAcces = async (tid) => { try { await apiClient.delete(`/contenus/${accesDe}/acces/${tid}`); chargerAcces(accesDe); charger(); } catch (e) { toast.error(extractError(e)); } };
  const contenuLecons = (liste || []).find((c) => c.id === leconsDe);
  const contenuAcces = (liste || []).find((c) => c.id === accesDe);

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
      {type === "info" && (
        <label className="flex items-center gap-2 text-sm rounded-lg border bg-white p-3" data-testid="reglage-diffusion">
          <input type="checkbox" checked={!!reglages.diffusion_wa} onChange={(e) => basculerDiffusion(e.target.checked)} />
          Envoyer chaque nouvelle info par WhatsApp aux clients dès sa date de publication (entre 7 h et 18 h, une seule fois)
        </label>
      )}
      {liste === null ? <div className="text-sm text-muted-foreground">Chargement…</div> : (
        <>
          <GrilleContenus contenus={affiches} vide="Aucun contenu. Cliquez sur « Nouveau »." />
          <div className="text-xs text-muted-foreground">Astuce : les cartes ci-dessus sont celles que voit le client. Gérez-les ci-dessous.</div>
          <div className="space-y-2">
            {affiches.map((c) => (
              <div key={c.id} className="flex flex-wrap items-center gap-2 rounded-lg border bg-white p-2 text-sm" data-testid="ligne-contenu">
                <span className="font-medium">{c.titre}</span>
                <span className="text-muted-foreground">{c.publie ? "Publié" : "Brouillon"}{c.type === "formation" ? ` · ${c.gratuit ? "gratuit" : `${c.prix} FCFA · ${c.achats} achat(s)`}` : ""}</span>
                {c.diffusion && <span className="text-xs text-muted-foreground">WhatsApp : {{ a_envoyer: "programmée", en_cours: "en cours", envoyee: `envoyée (${c.diffusion.nb_envoyes ?? 0})` }[c.diffusion.statut] || c.diffusion.statut}</span>}
                <Button variant="ghost" size="sm" className="ml-auto" onClick={() => setLeconsDe(c.id)}><ListVideo className="w-4 h-4 mr-1" />Leçons ({c.lecons?.length || 0})</Button>
                {c.type === "formation" && !c.gratuit && <Button variant="ghost" size="sm" onClick={() => ouvrirAcces(c.id)} data-testid="btn-acces"><KeyRound className="w-4 h-4 mr-1" />Accès</Button>}
                {c.type === "info" && c.publie && <Button variant="ghost" size="sm" onClick={() => diffuser(c)}><Send className="w-4 h-4 mr-1" />Diffuser</Button>}
                <Button variant="ghost" size="sm" onClick={() => basculer(c)}>{c.publie ? <><EyeOff className="w-4 h-4 mr-1" />Masquer</> : <><Eye className="w-4 h-4 mr-1" />Publier</>}</Button>
                {selection === c.id
                  ? <Button variant="destructive" size="sm" onClick={() => supprimer(c)}>Confirmer la suppression</Button>
                  : <Button variant="ghost" size="icon" onClick={() => setSelection(c.id)} aria-label="Supprimer"><Trash2 className="w-4 h-4" /></Button>}
              </div>
            ))}
          </div>
        </>
      )}

      {/* Leçons d'un contenu */}
      <Dialog open={!!leconsDe} onOpenChange={(o) => !o && setLeconsDe(null)}>
        <DialogContent className="max-w-xl max-h-[85dvh] overflow-y-auto">
          <DialogHeader><DialogTitle>Leçons — {contenuLecons?.titre}</DialogTitle></DialogHeader>
          <ol className="list-decimal pl-5 text-sm space-y-1">
            {(contenuLecons?.lecons || []).map((l) => (
              <li key={l.id}>{l.titre} <span className="text-muted-foreground">({l.format})</span>
                <button type="button" className="ml-2 text-rose-600" onClick={() => retirerLecon(l.id)} aria-label={`Retirer ${l.titre}`}><Trash2 className="w-3.5 h-3.5 inline" /></button></li>
            ))}
            {!contenuLecons?.lecons?.length && <li className="list-none text-muted-foreground">Aucune leçon pour le moment.</li>}
          </ol>
          <form onSubmit={ajouterLecon} className="space-y-2 text-sm border-t pt-3">
            <Input placeholder="Titre de la leçon" value={lecon.titre} onChange={(e) => setLecon({ ...lecon, titre: e.target.value })} data-testid="lecon-titre" />
            <Select value={lecon.format} onValueChange={(v) => setLecon({ ...lecon, format: v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>{opts.formats.filter((f) => f.code !== "serie").map((f) => <SelectItem key={f.code} value={f.code}>{f.libelle}</SelectItem>)}</SelectContent>
            </Select>
            {["video", "lien"].includes(lecon.format)
              ? <Input placeholder="Lien https://" value={lecon.url} onChange={(e) => setLecon({ ...lecon, url: e.target.value })} data-testid="lecon-url" />
              : <input type="file" accept={lecon.format === "pdf" ? ".pdf" : "audio/*"} onChange={(e) => setLeconFichier(e.target.files?.[0] || null)} />}
            <Button type="submit" className="bg-[#0F6B4A] hover:bg-[#0B5A3E]" data-testid="lecon-ajouter">Ajouter la leçon</Button>
          </form>
        </DialogContent>
      </Dialog>

      {/* Accès accordés à une formation payante */}
      <Dialog open={!!accesDe} onOpenChange={(o) => !o && setAccesDe(null)}>
        <DialogContent className="max-w-xl max-h-[85dvh] overflow-y-auto">
          <DialogHeader><DialogTitle>Accès — {contenuAcces?.titre}</DialogTitle></DialogHeader>
          <div className="flex gap-2 items-center text-sm">
            <Select value={clientChoisi} onValueChange={setClientChoisi}>
              <SelectTrigger data-testid="acces-client"><SelectValue placeholder="Choisir un client" /></SelectTrigger>
              <SelectContent>{clients.map((c) => <SelectItem key={c.id} value={c.id}>{c.company || c.full_name}</SelectItem>)}</SelectContent>
            </Select>
            <Button onClick={accorder} className="bg-[#0F6B4A] hover:bg-[#0B5A3E]" data-testid="acces-accorder">Accorder</Button>
          </div>
          <div className="space-y-1 text-sm">
            {acces.map((a) => (
              <div key={a.tenant_id + a.date} className="flex items-center gap-2 border rounded p-2">
                <span className="font-medium">{a.client}</span>
                <span className="text-muted-foreground">{a.source === "manuel" ? "accordé par le cabinet" : `payé ${Math.round(a.montant).toLocaleString("fr-FR")} FCFA`}</span>
                {a.source === "manuel" && <button type="button" className="ml-auto text-rose-600" onClick={() => retirerAcces(a.tenant_id)}>Retirer</button>}
              </div>
            ))}
            {!acces.length && <div className="text-muted-foreground">Aucun accès pour le moment.</div>}
          </div>
        </DialogContent>
      </Dialog>

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
