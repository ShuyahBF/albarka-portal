import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ChevronDown, ChevronRight, ListChecks, ClipboardList, Pencil, Trash2, Save, X, Bell } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";

import { Plus as Ico15Plus } from "lucide-react";
// Rôles qui peuvent consulter les tâches de tout le personnel (le superviseur l'est toujours côté serveur).
const ROLES_VUE_PERSONNEL = ["dg", "direction", "secretariat", "superviseur"];

// Cadre mince et bleu de tous les blocs d'information de cette rubrique.
const CADRE = "rounded-lg border border-blue-600 bg-white p-3";
// Couleur des cases à cocher (comme les listes de SAWALI / Google Keep).
const ORANGE = "#F59E0B";

// Heures proposées pour le rappel quotidien : liste finie => liste déroulante (règle 10), par pas de 30 min.
const HEURES = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);

// Date du jour AAAA-MM-JJ (pour repérer les tâches en retard)
const aujourdhui = () => new Date().toISOString().slice(0, 10);
// 2026-11-09 -> 09/11/2026
const fmtJour = (d) => (d ? d.slice(0, 10).split("-").reverse().join("/") : "—");
// Identifiant local d'un nouvel élément (le serveur le conserve)
const nouvelId = () => window.crypto?.randomUUID?.() || `t-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

// ---------------------------------------------------------------------
// Liste à cocher (comme SAWALI / Google Keep) : « Entrée » valide un élément ; les éléments faits
// descendent en bas, grisés et barrés.
// `surEntreeVide` : appelée quand on appuie sur Entrée dans un champ vide (sert à enregistrer la tâche en cours de saisie).
// ---------------------------------------------------------------------
export function ListeACocher({ elements, onChange, lectureSeule = false, surEntreeVide = null }) {
  const [brouillon, setBrouillon] = useState("");
  const tous = Array.isArray(elements) ? elements : [];
  // À faire d'abord (dans l'ordre), faits ensuite (le plus récemment fait en premier)
  const tries = useMemo(() => {
    const afaire = tous.filter((x) => !x.fait).sort((a, b) => (a.ordre || 0) - (b.ordre || 0));
    const faits = tous.filter((x) => x.fait).sort((a, b) => String(b.fait_le || "").localeCompare(String(a.fait_le || "")));
    return [...afaire, ...faits];
  }, [tous]);

  const ajouter = () => {
    const texte = brouillon.trim();
    if (!texte) return false;
    onChange([...tous, { id: nouvelId(), texte, fait: false, fait_le: null, ordre: tous.length }]);
    setBrouillon("");
    return true;
  };
  const cocher = (id) => onChange(tous.map((x) => (x.id === id ? { ...x, fait: !x.fait, fait_le: !x.fait ? new Date().toISOString() : null } : x)));
  const renommer = (id, texte) => onChange(tous.map((x) => (x.id === id ? { ...x, texte } : x)));
  const retirer = (id) => onChange(tous.filter((x) => x.id !== id));
  const nbFaits = tous.filter((x) => x.fait).length;

  return (
    <div className={`${CADRE} space-y-2`} data-testid="liste-a-cocher">
      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold text-slate-700 inline-flex items-center gap-1">
          <ClipboardList className="h-3.5 w-3.5" style={{ color: ORANGE }} /> Liste de tâches
        </span>
        <span className="text-slate-400">{nbFaits} fait(s) / {tous.length}</span>
      </div>
      {!lectureSeule && (
        <div className="flex gap-2">
          <input
            type="text"
            value={brouillon}
            maxLength={300}
            onChange={(e) => setBrouillon(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              e.preventDefault();
              if (!ajouter() && surEntreeVide) surEntreeVide();      // Entrée sur une ligne vide : enregistre la tâche
            }}
            placeholder="+ Ajouter un élément (Entrée pour valider)"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-blue-300"
            data-testid="liste-ajout-champ"
          />
          <button
            type="button"
            onClick={ajouter}
            disabled={!brouillon.trim()}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
            style={{ background: ORANGE }}
            data-testid="liste-ajout-bouton"
          >
            <Ico15Plus className="inline-block h-4 w-4 shrink-0 mr-1" aria-hidden="true" />Ajouter</button>
        </div>
      )}
      <ul className="space-y-1">
        {tries.length === 0 && <li className="text-xs text-slate-400 italic py-1 text-center">Aucun élément pour le moment.</li>}
        {tries.map((it) => (
          <li key={it.id} className={`flex items-center gap-2 rounded-lg px-2 py-1 ${it.fait ? "bg-slate-50" : "hover:bg-slate-50"}`} data-testid={`element-${it.id}`}>
            <input
              type="checkbox"
              checked={!!it.fait}
              disabled={lectureSeule}
              onChange={() => cocher(it.id)}
              className="h-4 w-4 cursor-pointer"
              style={{ accentColor: ORANGE }}
              aria-label="Élément réalisé"
              data-testid={`element-cocher-${it.id}`}
            />
            {lectureSeule ? (
              <span className={`flex-1 text-sm ${it.fait ? "line-through text-slate-400" : "text-slate-800"}`}>{it.texte}</span>
            ) : (
              <input
                type="text"
                value={it.texte}
                onChange={(e) => renommer(it.id, e.target.value)}
                className={`flex-1 bg-transparent text-sm outline-none border-0 ${it.fait ? "line-through text-slate-400" : "text-slate-800"}`}
              />
            )}
            {!lectureSeule && (
              <button type="button" onClick={() => retirer(it.id)} className="text-slate-300 hover:text-rose-500" title="Supprimer l'élément" data-testid={`element-retirer-${it.id}`}>
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------
// Bloc « Mes tâches » — replié à l'origine, réservé au personnel
// ---------------------------------------------------------------------
export default function TachesPersonnel({ user }) {
  const [ouvert, setOuvert] = useState(false);          // replié à l'origine
  const peutVoirTout = (user?.roles || []).some((r) => ROLES_VUE_PERSONNEL.includes(r));
  const [onglet, setOnglet] = useState("mes");          // mes | personnel

  return (
    <div className="albarka-card p-6 space-y-4 max-w-2xl" data-testid="taches-bloc">
      <button
        type="button"
        onClick={() => setOuvert((o) => !o)}
        aria-expanded={ouvert}
        className="w-full flex items-center justify-between font-semibold text-left"
        data-testid="taches-entete"
      >
        <span className="flex items-center gap-2"><ListChecks className="w-4 h-4" />Mes tâches</span>
        {ouvert ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
      </button>

      {ouvert && (
        <div className="space-y-4" data-testid="taches-contenu">
          {peutVoirTout && (
            <div className="flex gap-2 text-sm" role="tablist">
              {[["mes", "Mes tâches"], ["personnel", "Tâches du personnel"]].map(([cle, libelle]) => (
                <button
                  key={cle}
                  type="button"
                  role="tab"
                  aria-selected={onglet === cle}
                  onClick={() => setOnglet(cle)}
                  className={`rounded-full px-3 py-1 border ${onglet === cle ? "bg-blue-600 text-white border-blue-600" : "border-blue-600 text-blue-700"}`}
                  data-testid={`taches-onglet-${cle}`}
                >
                  {libelle}
                </button>
              ))}
            </div>
          )}
          {onglet === "mes" ? <MesTaches /> : <TachesDuPersonnel />}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// Mes tâches : rappel quotidien + saisie rapide (Entrée) + cartes
// ---------------------------------------------------------------------
function MesTaches() {
  const [taches, setTaches] = useState([]);
  const [chargement, setChargement] = useState(true);
  const [rappel, setRappel] = useState({ actif: false, heure: "08:00" });
  const [filtre, setFiltre] = useState("toutes");        // toutes | a_faire | fait
  const [enCours, setEnCours] = useState(false);

  const charger = useCallback(async () => {
    setChargement(true);
    try {
      const [t, r] = await Promise.all([apiClient.get("/me/taches"), apiClient.get("/me/taches/rappel")]);
      setTaches(t.data);
      setRappel(r.data);
    } catch (err) {
      toast.error(extractError(err));
    } finally { setChargement(false); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Création : titre seul = texte libre ; titre + éléments = liste à cocher
  const creer = async (brouillon) => {
    if (!brouillon.titre.trim()) { toast.error("Saisissez d'abord le titre de la tâche"); return false; }
    setEnCours(true);
    try {
      await apiClient.post("/me/taches", {
        titre: brouillon.titre, details: brouillon.details, echeance: brouillon.echeance || null, elements: brouillon.elements,
      });
      await charger();
      toast.success("Tâche ajoutée");
      return true;
    } catch (err) { toast.error(extractError(err)); return false; } finally { setEnCours(false); }
  };

  // Enregistrement immédiat d'un changement (case cochée, élément ajouté, tâche modifiée…)
  const modifier = async (id, corps) => {
    try {
      const { data } = await apiClient.patch(`/me/taches/${id}`, corps);
      setTaches((liste) => liste.map((t) => (t.id === id ? { ...t, ...data } : t)));
    } catch (err) { toast.error(extractError(err)); await charger(); }
  };

  const supprimer = async (t) => {
    if (!window.confirm(`Supprimer la tâche « ${t.titre} » ?`)) return;
    try { await apiClient.delete(`/me/taches/${t.id}`); await charger(); toast.success("Tâche supprimée"); }
    catch (err) { toast.error(extractError(err)); }
  };

  // Réglage du rappel : enregistré dès qu'on change l'interrupteur ou l'heure
  const regler = async (suite) => {
    const prochain = { ...rappel, ...suite };
    setRappel(prochain);
    try {
      await apiClient.put("/me/taches/rappel", prochain);
      toast.success(prochain.actif ? `Rappel quotidien à ${prochain.heure}` : "Rappel quotidien désactivé");
    } catch (err) { toast.error(extractError(err)); await charger(); }
  };

  const visibles = taches.filter((t) => filtre === "toutes" || t.statut === filtre);

  return (
    <div className="space-y-4">
      {/* Rappel quotidien, réglé par la personne elle-même */}
      <div className={`${CADRE} space-y-2`} data-testid="taches-rappel">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Switch checked={rappel.actif} onCheckedChange={(v) => regler({ actif: v })} data-testid="taches-rappel-switch" />
          <span className="flex items-center gap-1"><Bell className="w-4 h-4" />Me rappeler mes tâches chaque jour</span>
        </label>
        {rappel.actif && (
          <div className="flex items-center gap-2 text-sm pl-1">
            <span>Heure d&apos;envoi :</span>
            <select value={rappel.heure} onChange={(e) => regler({ heure: e.target.value })}
              className="rounded-md border border-slate-300 px-2 py-1" data-testid="taches-rappel-heure">
              {HEURES.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
            <span className="text-xs text-muted-foreground">(heure du Burkina Faso, GMT)</span>
          </div>
        )}
        <p className="text-xs text-muted-foreground">Envoyé par WhatsApp (ou par e-mail à défaut) seulement s&apos;il vous reste des tâches à réaliser.</p>
      </div>

      <NouvelleTache onCreer={creer} enCours={enCours} />

      <div className="flex items-center gap-2 text-sm">
        <Label className="text-xs">Afficher</Label>
        <select value={filtre} onChange={(e) => setFiltre(e.target.value)} className="rounded-md border border-slate-300 px-2 py-1" data-testid="taches-filtre">
          <option value="toutes">Toutes</option>
          <option value="a_faire">À faire</option>
          <option value="fait">Réalisées</option>
        </select>
      </div>

      {chargement ? (
        <div className="text-sm text-muted-foreground">Chargement…</div>
      ) : visibles.length === 0 ? (
        <div className={`${CADRE} text-sm text-muted-foreground`} data-testid="taches-vide">Aucune tâche pour l&apos;instant.</div>
      ) : (
        <div className="space-y-3" data-testid="taches-liste">
          {visibles.map((t) => <CarteTache key={t.id} tache={t} onModifier={modifier} onSupprimer={supprimer} />)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// Saisie d'une nouvelle tâche. « Entrée » dans le titre enregistre tout de suite (tâche en texte libre) ;
// pour une liste : ajouter des éléments (Entrée), puis Entrée sur une ligne vide enregistre la tâche.
// ---------------------------------------------------------------------
function NouvelleTache({ onCreer, enCours }) {
  const vide = { titre: "", details: "", echeance: "", elements: [] };
  const [b, setB] = useState(vide);
  const enregistrer = async () => { if (await onCreer(b)) setB(vide); };

  return (
    <div className={`${CADRE} space-y-2`} data-testid="taches-nouvelle">
      <Label>Nouvelle tâche</Label>
      <Input
        placeholder="Titre de la tâche — Entrée pour l'enregistrer"
        value={b.titre}
        maxLength={200}
        onChange={(e) => setB({ ...b, titre: e.target.value })}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); enregistrer(); } }}
        data-testid="taches-titre"
      />
      <Textarea
        placeholder="Détails en texte libre (facultatif) — Ctrl + Entrée pour enregistrer"
        rows={2}
        value={b.details}
        onChange={(e) => setB({ ...b, details: e.target.value })}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); enregistrer(); } }}
        data-testid="taches-details"
      />
      <ListeACocher elements={b.elements} onChange={(elements) => setB({ ...b, elements })} surEntreeVide={enregistrer} />
      <div className="flex items-end gap-3 flex-wrap">
        <div>
          <Label className="text-xs">Échéance (facultative)</Label>
          <Input type="date" value={b.echeance} onChange={(e) => setB({ ...b, echeance: e.target.value })}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); enregistrer(); } }} data-testid="taches-echeance" />
        </div>
        <Button onClick={enregistrer} disabled={enCours} variant="outline" data-testid="taches-ajouter">{enCours ? "Patientez…" : "Enregistrer la tâche"}</Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Une tâche : titre, échéance, texte libre, liste à cocher ; modification en place
// ---------------------------------------------------------------------
function CarteTache({ tache: t, onModifier, onSupprimer }) {
  const [edition, setEdition] = useState(null);
  const jour = aujourdhui();
  const avecListe = (t.elements || []).length > 0;
  const enRetard = t.statut !== "fait" && t.echeance && t.echeance < jour;

  if (edition) {
    return (
      <div className={`${CADRE} space-y-2`} data-testid={`tache-edition-${t.id}`}>
        <div className="font-semibold text-sm">Modifier tâche</div>
        <Input value={edition.titre} maxLength={200} onChange={(e) => setEdition({ ...edition, titre: e.target.value })}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); enregistrer(); } }} />
        <Textarea rows={2} value={edition.details || ""} onChange={(e) => setEdition({ ...edition, details: e.target.value })} />
        <ListeACocher elements={edition.elements} onChange={(elements) => setEdition({ ...edition, elements })} />
        <div className="flex items-end gap-3 flex-wrap">
          <Input type="date" className="w-auto" value={edition.echeance || ""} onChange={(e) => setEdition({ ...edition, echeance: e.target.value })} />
          <Button onClick={enregistrer} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="tache-enregistrer"><Save className="w-4 h-4 mr-1" />Enregistrer</Button>
          <Button variant="outline" onClick={() => setEdition(null)}><X className="w-4 h-4 mr-1" />Annuler</Button>
        </div>
      </div>
    );
  }

  async function enregistrer() {
    if (!edition.titre.trim()) { toast.error("Le titre est requis"); return; }
    await onModifier(t.id, { titre: edition.titre, details: edition.details || "", echeance: edition.echeance || "", elements: edition.elements });
    setEdition(null);
  }

  return (
    <div className={`${CADRE} space-y-2`} data-testid={`tache-${t.id}`}>
      <div className="flex items-start gap-2">
        {!avecListe && (
          <input type="checkbox" checked={t.statut === "fait"} onChange={() => onModifier(t.id, { statut: t.statut === "fait" ? "a_faire" : "fait" })}
            className="mt-1 h-4 w-4 cursor-pointer" style={{ accentColor: ORANGE }} aria-label="Tâche réalisée" data-testid={`tache-cocher-${t.id}`} />
        )}
        <div className="flex-1 min-w-0">
          <div className={t.statut === "fait" ? "line-through text-muted-foreground" : "font-medium"}>{t.titre}</div>
          <div className={`text-xs ${enRetard ? "text-red-600 font-medium" : "text-muted-foreground"}`}>
            {t.echeance ? `Échéance ${fmtJour(t.echeance)}${enRetard ? " (en retard)" : ""}` : "Sans échéance"}
            {t.statut === "fait" && t.realisee_le ? ` · Réalisée le ${fmtJour(t.realisee_le)}` : ""}
          </div>
          {t.details && <div className="text-sm text-slate-600 whitespace-pre-wrap mt-1">{t.details}</div>}
        </div>
        <button type="button" title="Modifier" onClick={() => setEdition({ titre: t.titre, details: t.details, echeance: t.echeance, elements: t.elements || [] })}
          data-testid={`tache-modifier-${t.id}`}><Pencil className="w-4 h-4" /></button>
        <button type="button" title="Supprimer" onClick={() => onSupprimer(t)} data-testid={`tache-supprimer-${t.id}`}><Trash2 className="w-4 h-4 text-red-600" /></button>
      </div>
      {avecListe && <ListeACocher elements={t.elements} onChange={(elements) => onModifier(t.id, { elements })} />}
    </div>
  );
}

// ---------------------------------------------------------------------
// DG / Direction / Secrétariat : choisir un membre du personnel et voir ses tâches (lecture seule)
// ---------------------------------------------------------------------
function TachesDuPersonnel() {
  const [personnel, setPersonnel] = useState([]);
  const [choix, setChoix] = useState("");
  const [fiche, setFiche] = useState(null);
  const [chargement, setChargement] = useState(false);

  useEffect(() => {
    apiClient.get("/me/taches/personnel").then((r) => setPersonnel(r.data)).catch((err) => toast.error(extractError(err)));
  }, []);

  // Charge les tâches du membre choisi
  useEffect(() => {
    if (!choix) { setFiche(null); return; }
    setChargement(true);
    apiClient.get(`/me/taches/personnel/${choix}`)
      .then((r) => setFiche(r.data))
      .catch((err) => toast.error(extractError(err)))
      .finally(() => setChargement(false));
  }, [choix]);

  const taches = fiche?.taches || [];
  const nonRealisees = taches.filter((t) => t.statut !== "fait");
  const realisees = taches.filter((t) => t.statut === "fait");

  return (
    <div className="space-y-4" data-testid="taches-personnel">
      <div className={CADRE}>
        <Label>Membre du personnel</Label>
        <select value={choix} onChange={(e) => setChoix(e.target.value)}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" data-testid="taches-select-membre">
          <option value="">— Choisir un membre —</option>
          {personnel.map((m) => (
            <option key={m.id} value={m.id}>{m.full_name || m.email} ({m.a_faire} à faire · {m.faites} faites)</option>
          ))}
        </select>
      </div>
      {chargement && <div className="text-sm text-muted-foreground">Chargement…</div>}
      {fiche && !chargement && (
        <>
          <SectionLecture titre={`Non réalisées (${nonRealisees.length})`} taches={nonRealisees} testid="taches-non-realisees" />
          <SectionLecture titre={`Réalisées (${realisees.length})`} taches={realisees} testid="taches-realisees" />
        </>
      )}
    </div>
  );
}

// Liste en lecture seule d'un groupe de tâches (échéance, date de réalisation, liste à cocher)
function SectionLecture({ titre, taches, testid }) {
  const jour = aujourdhui();
  return (
    <div className={`${CADRE} space-y-2`} data-testid={testid}>
      <div className="font-semibold text-sm">{titre}</div>
      {taches.length === 0 ? <div className="text-sm text-muted-foreground">Aucune.</div> : taches.map((t) => {
        const enRetard = t.statut !== "fait" && t.echeance && t.echeance < jour;
        return (
          <div key={t.id} className="rounded-lg border border-blue-600 p-2 space-y-1">
            <div className={t.statut === "fait" ? "line-through text-muted-foreground" : "font-medium"}>{t.titre}</div>
            <div className={`text-xs ${enRetard ? "text-red-600 font-medium" : "text-muted-foreground"}`}>
              {t.statut === "fait" ? `Réalisée le ${fmtJour(t.realisee_le)}` : t.echeance ? `Échéance ${fmtJour(t.echeance)}${enRetard ? " (en retard)" : ""}` : "Sans échéance"}
            </div>
            {t.details && <div className="text-sm text-slate-600 whitespace-pre-wrap">{t.details}</div>}
            {(t.elements || []).length > 0 && <ListeACocher elements={t.elements} lectureSeule onChange={() => {}} />}
          </div>
        );
      })}
    </div>
  );
}
