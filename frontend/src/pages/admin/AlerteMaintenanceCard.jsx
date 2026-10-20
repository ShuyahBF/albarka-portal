/*
  Lot 44 — Paramètres (super-admin seul) : « Alerte / incident » et « Déconnexion programmée ».
  1. Bandeau d'alerte : message + gravité (liste déroulante) + image facultative (coin gauche) + lien facultatif.
  2. Déconnexion programmée : message + durée (minutes) + part de la durée pendant laquelle l'écran est verrouillé
     (5 % par défaut). Boutons Annoncer / Annuler (avant l'échéance) / Réactiver les connexions (après).
  Lecture / écriture : /api/bandeau et /api/maintenance/* (réservés au super-admin côté serveur).
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Megaphone, Wrench, Trash2, Upload } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

const GRAVITES = [
  { v: "info", t: "Information" },
  { v: "warning", t: "Avertissement" },
  { v: "critical", t: "Critique" },
];
const FOND = { info: "bg-sky-600 text-white", warning: "bg-amber-500 text-slate-900", critical: "bg-rose-600 text-white" };
const PHASES = { aucune: "Aucune déconnexion programmée", annonce: "Annoncée — les utilisateurs sont prévenus", verrouillage: "Écran verrouillé — décompte en cours", maintenance: "En maintenance — connexions suspendues" };
// Lot 46 : ISO (serveur) <-> valeur d'un champ « datetime-local » (heure locale du navigateur)
const versChamp = (iso) => { if (!iso) return ""; const d = new Date(iso); const p = (n) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };
const versIso = (champ) => (champ ? new Date(champ).toISOString() : null);
const STATUTS = { programme: "⏳ Programmé : pas encore affiché", affiche: "✅ Affiché en ce moment", termine: "⏹ Terminé : plus affiché" };
const dateFr = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");

export default function AlerteMaintenanceCard() {
  const [b, setB] = useState({ message: "", severite: "warning", image: "", lien_url: "", lien_libelle: "", debut: "", fin: "" });
  const [statutB, setStatutB] = useState("aucun");
  const [actif, setActif] = useState(false);
  const [etat, setEtat] = useState(null);
  const [m, setM] = useState({ message: "", duree_minutes: 5, part_verrouillage: 5 });
  const [journal, setJournal] = useState([]);
  const [occupe, setOccupe] = useState(false);

  const charger = useCallback(async () => {
    try {
      const [bd, et, jr] = await Promise.all([apiClient.get("/bandeau/admin"), apiClient.get("/maintenance/etat"), apiClient.get("/maintenance/journal")]);
      setActif(!!bd.data?.actif); setStatutB(bd.data?.statut || "aucun");
      if (bd.data?.actif) setB({ message: bd.data.message || "", severite: bd.data.severite || "warning", image: bd.data.image || "", lien_url: bd.data.lien_url || "", lien_libelle: bd.data.lien_libelle || "", debut: versChamp(bd.data.debut), fin: versChamp(bd.data.fin) });
      setEtat(et.data); setJournal(jr.data?.journal || []);
    } catch (e) { toast.error(extractError(e, "Lecture impossible")); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  const agir = async (fn, ok) => {
    setOccupe(true);
    try { await fn(); toast.success(ok); await charger(); } catch (e) { toast.error(extractError(e)); } finally { setOccupe(false); }
  };

  // Image du bandeau : lue en « data URI » (400 Ko au plus, contrôlé aussi par le serveur)
  const choisirImage = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 400000) { toast.error("Image trop lourde (400 Ko au plus)"); return; }
    const lecteur = new FileReader();
    lecteur.onload = () => setB((x) => ({ ...x, image: String(lecteur.result) }));
    lecteur.readAsDataURL(f);
  };

  const phase = etat?.phase || "aucune";
  return (
    <div className="space-y-6 max-w-2xl" data-testid="alerte-maintenance">
      {/* ---------- Bandeau d'alerte ---------- */}
      <div className="albarka-card p-6 space-y-3" data-testid="bandeau-admin">
        <div className="flex items-center gap-2 font-semibold"><Megaphone className="h-4 w-4" /> Alerte / incident (bandeau en haut du portail)</div>
        <div className="text-sm text-muted-foreground">Le message s'affiche chez tous les utilisateurs et sur la page de connexion, jusqu'à ce que vous le retiriez.</div>
        <div><Label>Message</Label>
          <Textarea rows={2} maxLength={1000} value={b.message} onChange={(e) => setB({ ...b, message: e.target.value })} data-testid="bandeau-message" /></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div><Label>Gravité</Label>
            <select value={b.severite} onChange={(e) => setB({ ...b, severite: e.target.value })} className="h-9 w-full rounded-md border border-input bg-white px-2 text-sm" data-testid="bandeau-gravite">
              {GRAVITES.map((g) => <option key={g.v} value={g.v}>{g.t}</option>)}
            </select></div>
          <div><Label>Image (coin gauche, facultative)</Label>
            <div className="flex items-center gap-2">
              <label className="inline-flex h-9 cursor-pointer items-center gap-1 rounded-md border border-input bg-white px-3 text-sm"><Upload className="h-4 w-4" /> Choisir
                <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden" onChange={choisirImage} data-testid="bandeau-image" /></label>
              {b.image && <button type="button" onClick={() => setB({ ...b, image: "" })} className="text-xs underline">Retirer l'image</button>}
            </div></div>
          <div><Label>Lien (facultatif)</Label>
            <Input value={b.lien_url} placeholder="https://…" onChange={(e) => setB({ ...b, lien_url: e.target.value })} /></div>
          <div><Label>Texte du lien</Label>
            <Input value={b.lien_libelle} placeholder="En savoir plus" onChange={(e) => setB({ ...b, lien_libelle: e.target.value })} /></div>
        </div>
        {/* Lot 46 : programmation — jour et heure d'affichage (vide = tout de suite / jusqu'au retrait) */}
        <div className="grid gap-3 sm:grid-cols-2">
          <div><Label>Afficher à partir du (facultatif)</Label>
            <Input type="datetime-local" value={b.debut} onChange={(e) => setB({ ...b, debut: e.target.value })} data-testid="bandeau-debut" /></div>
          <div><Label>Jusqu'au (facultatif)</Label>
            <Input type="datetime-local" value={b.fin} onChange={(e) => setB({ ...b, fin: e.target.value })} data-testid="bandeau-fin" /></div>
        </div>
        {actif && <div className="text-sm" data-testid="bandeau-statut">{STATUTS[statutB]}{b.debut && statutB === "programme" ? ` — début le ${dateFr(versIso(b.debut))}` : ""}</div>}
        {/* Aperçu fidèle du bandeau */}
        {b.message.trim() && (
          <div className={`rounded-md px-3 py-2 flex items-center gap-3 text-sm font-medium ${FOND[b.severite]}`} data-testid="bandeau-apercu">
            {b.image && <img src={b.image} alt="" className="h-10 w-10 shrink-0 rounded-md object-cover bg-white/20" />}
            <span className="min-w-0 break-words">{b.message}</span>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button disabled={occupe || !b.message.trim()} data-testid="bandeau-publier"
            onClick={() => agir(() => apiClient.put("/bandeau", { ...b, image: b.image || null, lien_url: b.lien_url || null, lien_libelle: b.lien_libelle || null, debut: versIso(b.debut), fin: versIso(b.fin) }), "Bandeau publié")}>
            {b.debut ? "Programmer le bandeau" : actif ? "Mettre à jour le bandeau" : "Publier le bandeau"}</Button>
          {actif && <Button variant="outline" disabled={occupe} data-testid="bandeau-retirer" onClick={() => agir(async () => { await apiClient.delete("/bandeau"); setB({ message: "", severite: "warning", image: "", lien_url: "", lien_libelle: "", debut: "", fin: "" }); }, "Bandeau retiré")}>
            <Trash2 className="h-4 w-4 mr-1" /> Retirer le bandeau</Button>}
        </div>
      </div>

      {/* ---------- Déconnexion programmée ---------- */}
      <div className="albarka-card p-6 space-y-3" data-testid="maintenance-admin">
        <div className="flex items-center gap-2 font-semibold"><Wrench className="h-4 w-4" /> Déconnexion programmée des utilisateurs</div>
        <div className={`rounded-md px-3 py-2 text-sm ${phase === "aucune" ? "bg-slate-100" : "bg-rose-50 text-rose-900"}`} data-testid="maintenance-etat">
          {PHASES[phase]}{etat?.active && phase !== "maintenance" && <> — échéance le {dateFr(etat.echeance)}</>}
        </div>
        {phase === "aucune" && (
          <>
            <div><Label>Message affiché aux utilisateurs</Label>
              <Textarea rows={2} maxLength={1000} value={m.message} onChange={(e) => setM({ ...m, message: e.target.value })} placeholder="Maintenance du portail : enregistrez votre travail." data-testid="maintenance-message" /></div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div><Label>Durée avant la déconnexion (1 à 120 minutes)</Label>
                <Input type="number" min={1} max={120} value={m.duree_minutes} onChange={(e) => setM({ ...m, duree_minutes: Number(e.target.value) })} data-testid="maintenance-duree" /></div>
              <div><Label>Écran verrouillé les derniers (% de la durée)</Label>
                <Input type="number" min={0} max={100} value={m.part_verrouillage} onChange={(e) => setM({ ...m, part_verrouillage: Number(e.target.value) })} data-testid="maintenance-part" /></div>
            </div>
            <Button disabled={occupe || !m.message.trim()} data-testid="maintenance-annoncer"
              onClick={() => { if (window.confirm(`Tous les utilisateurs (sauf vous) seront déconnectés dans ${m.duree_minutes} minute(s). Annoncer ?`)) agir(() => apiClient.post("/maintenance/annoncer", m), "Déconnexion annoncée"); }}>
              Annoncer la déconnexion</Button>
          </>
        )}
        {(phase === "annonce" || phase === "verrouillage") && (
          <Button variant="outline" disabled={occupe} data-testid="maintenance-annuler" onClick={() => agir(() => apiClient.post("/maintenance/annuler"), "Déconnexion annulée")}>Annuler la déconnexion</Button>
        )}
        {phase === "maintenance" && (
          <Button disabled={occupe} data-testid="maintenance-reactiver"
            onClick={() => { if (window.confirm("Rouvrir la connexion ? Chaque utilisateur devra se reconnecter.")) agir(() => apiClient.post("/maintenance/reactiver"), "Connexions rétablies"); }}>
            Réactiver les connexions</Button>
        )}
        <p className="text-xs text-muted-foreground">Vous n'êtes jamais déconnecté : seul le super-admin peut se reconnecter pendant la maintenance et rouvrir la connexion.</p>
        {journal.length > 0 && (
          <ul className="text-xs text-muted-foreground space-y-0.5" data-testid="maintenance-journal">
            {journal.slice(0, 8).map((l) => <li key={l.id}>{dateFr(l.date)} — {l.action} par {l.par?.nom}{l.message ? ` : « ${l.message.slice(0, 60)} »` : ""}</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}
