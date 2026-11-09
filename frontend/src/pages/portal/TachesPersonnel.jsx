import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ChevronDown, ChevronRight, ListChecks, Plus, Pencil, Trash2, Save, X, Bell } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";

// Rôles qui peuvent consulter les tâches de tout le personnel (le superviseur l'est toujours côté serveur).
const ROLES_VUE_PERSONNEL = ["dg", "direction", "secretariat", "superviseur"];

// Heures proposées pour le rappel quotidien : liste finie => liste déroulante (règle 10), par pas de 30 min.
const HEURES = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);

// Date du jour AAAA-MM-JJ (pour repérer les tâches en retard)
const aujourdhui = () => new Date().toISOString().slice(0, 10);
// 2026-11-09 -> 09/11/2026
const fmtJour = (d) => (d ? d.slice(0, 10).split("-").reverse().join("/") : "—");

// Tri d'un tableau : clic sur l'en-tête (règle 3), ▲ / ▼ sur la colonne triée.
function useTri(lignes, defaut) {
  const [tri, setTri] = useState(defaut);
  const triees = useMemo(() => {
    const copie = [...lignes];
    copie.sort((a, b) => {
      const va = a[tri.cle] ?? "";
      const vb = b[tri.cle] ?? "";
      return (va < vb ? -1 : va > vb ? 1 : 0) * (tri.sens === "asc" ? 1 : -1);
    });
    return copie;
  }, [lignes, tri]);
  const basculer = (cle) => setTri((t) => (t.cle === cle ? { cle, sens: t.sens === "asc" ? "desc" : "asc" } : { cle, sens: "asc" }));
  return { triees, tri, basculer };
}

function EnTete({ cle, tri, basculer, children }) {
  const actif = tri.cle === cle;
  return (
    <th
      className={`px-3 py-2 text-left font-medium cursor-pointer select-none ${actif ? "text-orange-600" : ""}`}
      onClick={() => basculer(cle)}
      data-testid={`taches-tri-${cle}`}
    >
      {children} {actif ? (tri.sens === "asc" ? "▲" : "▼") : ""}
    </th>
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
                  className={`rounded-full px-3 py-1 border ${onglet === cle ? "bg-[#0F6B4A] text-white border-[#0F6B4A]" : "border-slate-300"}`}
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
// Mes tâches : rappel quotidien + création + liste
// ---------------------------------------------------------------------
function MesTaches() {
  const [taches, setTaches] = useState([]);
  const [chargement, setChargement] = useState(true);
  const [rappel, setRappel] = useState({ actif: false, heure: "08:00" });
  const [form, setForm] = useState({ titre: "", details: "", echeance: "" });
  const [edition, setEdition] = useState(null);          // tâche en cours de modification
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

  const ajouter = async () => {
    if (!form.titre.trim()) { toast.error("Le titre est requis"); return; }
    setEnCours(true);
    try {
      await apiClient.post("/me/taches", { titre: form.titre, details: form.details, echeance: form.echeance || null });
      setForm({ titre: "", details: "", echeance: "" });
      await charger();
      toast.success("Tâche ajoutée");
    } catch (err) { toast.error(extractError(err)); } finally { setEnCours(false); }
  };

  const cocher = async (t) => {
    try {
      await apiClient.patch(`/me/taches/${t.id}`, { statut: t.statut === "fait" ? "a_faire" : "fait" });
      await charger();
    } catch (err) { toast.error(extractError(err)); }
  };

  const enregistrerEdition = async () => {
    if (!edition.titre.trim()) { toast.error("Le titre est requis"); return; }
    try {
      await apiClient.patch(`/me/taches/${edition.id}`, { titre: edition.titre, details: edition.details || "", echeance: edition.echeance || "" });
      setEdition(null);
      await charger();
      toast.success("Tâche modifiée");
    } catch (err) { toast.error(extractError(err)); }
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

  const { triees, tri, basculer } = useTri(taches, { cle: "echeance", sens: "asc" });
  const jour = aujourdhui();

  return (
    <div className="space-y-4">
      {/* Rappel quotidien, réglé par la personne elle-même */}
      <div className="rounded-lg border border-slate-200 p-3 space-y-2" data-testid="taches-rappel">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Switch checked={rappel.actif} onCheckedChange={(v) => regler({ actif: v })} data-testid="taches-rappel-switch" />
          <span className="flex items-center gap-1"><Bell className="w-4 h-4" />Me rappeler mes tâches chaque jour</span>
        </label>
        {rappel.actif && (
          <div className="flex items-center gap-2 text-sm pl-1">
            <span>Heure d&apos;envoi :</span>
            <select
              value={rappel.heure}
              onChange={(e) => regler({ heure: e.target.value })}
              className="rounded-md border border-slate-300 px-2 py-1"
              data-testid="taches-rappel-heure"
            >
              {HEURES.map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
            <span className="text-xs text-muted-foreground">(heure du Burkina Faso, GMT)</span>
          </div>
        )}
        <p className="text-xs text-muted-foreground">Envoyé par WhatsApp (ou par e-mail à défaut) seulement s&apos;il vous reste des tâches à réaliser.</p>
      </div>

      {/* Nouvelle tâche */}
      <div className="space-y-2" data-testid="taches-nouvelle">
        <Label>Nouvelle tâche</Label>
        <Input placeholder="Titre de la tâche" value={form.titre} maxLength={200}
          onChange={(e) => setForm({ ...form, titre: e.target.value })} data-testid="taches-titre" />
        <Textarea placeholder="Détails (facultatif)" rows={2} value={form.details}
          onChange={(e) => setForm({ ...form, details: e.target.value })} data-testid="taches-details" />
        <div className="flex items-end gap-3 flex-wrap">
          <div>
            <Label className="text-xs">Échéance (facultative)</Label>
            <Input type="date" value={form.echeance} onChange={(e) => setForm({ ...form, echeance: e.target.value })} data-testid="taches-echeance" />
          </div>
          <Button onClick={ajouter} disabled={enCours} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="taches-ajouter">
            <Plus className="w-4 h-4 mr-1" />{enCours ? "Patientez…" : "Ajouter"}
          </Button>
        </div>
      </div>

      {/* Liste */}
      {chargement ? (
        <div className="text-sm text-muted-foreground">Chargement…</div>
      ) : triees.length === 0 ? (
        <div className="text-sm text-muted-foreground" data-testid="taches-vide">Aucune tâche pour l&apos;instant.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="tableau w-full text-sm" data-testid="taches-table">
            <thead>
              <tr className="border-b">
                <th className="px-3 py-2 w-8" />
                <EnTete cle="titre" tri={tri} basculer={basculer}>Tâche</EnTete>
                <EnTete cle="echeance" tri={tri} basculer={basculer}>Échéance</EnTete>
                <EnTete cle="realisee_le" tri={tri} basculer={basculer}>Réalisée le</EnTete>
                <th className="px-3 py-2 w-20" />
              </tr>
            </thead>
            <tbody>
              {triees.map((t) => {
                const enRetard = t.statut !== "fait" && t.echeance && t.echeance < jour;
                return edition?.id === t.id ? (
                  <tr key={t.id} className="border-b align-top" data-testid={`tache-edition-${t.id}`}>
                    <td />
                    <td className="px-3 py-2 space-y-1">
                      <Input value={edition.titre} onChange={(e) => setEdition({ ...edition, titre: e.target.value })} />
                      <Textarea rows={2} value={edition.details || ""} onChange={(e) => setEdition({ ...edition, details: e.target.value })} />
                    </td>
                    <td className="px-3 py-2">
                      <Input type="date" value={edition.echeance || ""} onChange={(e) => setEdition({ ...edition, echeance: e.target.value })} />
                    </td>
                    <td />
                    <td className="px-3 py-2 whitespace-nowrap">
                      <button type="button" title="Enregistrer" onClick={enregistrerEdition} data-testid="tache-enregistrer"><Save className="w-4 h-4 text-emerald-700" /></button>{" "}
                      <button type="button" title="Annuler" onClick={() => setEdition(null)}><X className="w-4 h-4" /></button>
                    </td>
                  </tr>
                ) : (
                  <tr key={t.id} className="border-b align-top" data-testid={`tache-${t.id}`}>
                    <td className="px-3 py-2">
                      <input type="checkbox" checked={t.statut === "fait"} onChange={() => cocher(t)}
                        aria-label="Tâche réalisée" data-testid={`tache-cocher-${t.id}`} />
                    </td>
                    <td className="px-3 py-2">
                      <div className={t.statut === "fait" ? "line-through text-muted-foreground" : "font-medium"}>{t.titre}</div>
                      {t.details && <div className="text-xs text-muted-foreground whitespace-pre-wrap">{t.details}</div>}
                    </td>
                    <td className={`px-3 py-2 whitespace-nowrap ${enRetard ? "text-red-600 font-medium" : ""}`}>
                      {fmtJour(t.echeance)}{enRetard ? " (en retard)" : ""}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">{fmtJour(t.realisee_le)}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <button type="button" title="Modifier" onClick={() => setEdition({ ...t })} data-testid={`tache-modifier-${t.id}`}><Pencil className="w-4 h-4" /></button>{" "}
                      <button type="button" title="Supprimer" onClick={() => supprimer(t)} data-testid={`tache-supprimer-${t.id}`}><Trash2 className="w-4 h-4 text-red-600" /></button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------
// DG / Direction / Secrétariat : choisir un membre du personnel et voir ses tâches
// ---------------------------------------------------------------------
function TachesDuPersonnel() {
  const [personnel, setPersonnel] = useState([]);
  const [choix, setChoix] = useState("");
  const [fiche, setFiche] = useState(null);
  const [chargement, setChargement] = useState(false);

  useEffect(() => {
    apiClient.get("/me/taches/personnel").then((r) => setPersonnel(r.data)).catch((err) => toast.error(extractError(err)));
  }, []);

  // Charge les tâches du membre choisi (lecture seule)
  useEffect(() => {
    if (!choix) { setFiche(null); return; }
    setChargement(true);
    apiClient.get(`/me/taches/personnel/${choix}`)
      .then((r) => setFiche(r.data))
      .catch((err) => toast.error(extractError(err)))
      .finally(() => setChargement(false));
  }, [choix]);

  const jour = aujourdhui();
  const taches = fiche?.taches || [];
  const nonRealisees = taches.filter((t) => t.statut !== "fait");
  const realisees = taches.filter((t) => t.statut === "fait");

  return (
    <div className="space-y-4" data-testid="taches-personnel">
      <div>
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
          <ListeLecture titre={`Non réalisées (${nonRealisees.length})`} lignes={nonRealisees} colonneDate="echeance" libelleDate="Échéance" jour={jour} testid="taches-non-realisees" />
          <ListeLecture titre={`Réalisées (${realisees.length})`} lignes={realisees} colonneDate="realisee_le" libelleDate="Réalisée le" jour={jour} testid="taches-realisees" />
        </>
      )}
    </div>
  );
}

// Tableau en lecture seule, triable par clic sur l'en-tête
function ListeLecture({ titre, lignes, colonneDate, libelleDate, jour, testid }) {
  const { triees, tri, basculer } = useTri(lignes, { cle: colonneDate, sens: colonneDate === "realisee_le" ? "desc" : "asc" });
  return (
    <div data-testid={testid}>
      <div className="font-semibold text-sm mb-1">{titre}</div>
      {triees.length === 0 ? (
        <div className="text-sm text-muted-foreground">Aucune.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="tableau w-full text-sm">
            <thead>
              <tr className="border-b">
                <EnTete cle="titre" tri={tri} basculer={basculer}>Tâche</EnTete>
                <EnTete cle={colonneDate} tri={tri} basculer={basculer}>{libelleDate}</EnTete>
              </tr>
            </thead>
            <tbody>
              {triees.map((t) => {
                const enRetard = colonneDate === "echeance" && t.echeance && t.echeance < jour;
                return (
                  <tr key={t.id} className="border-b align-top">
                    <td className="px-3 py-2">
                      <div className="font-medium">{t.titre}</div>
                      {t.details && <div className="text-xs text-muted-foreground whitespace-pre-wrap">{t.details}</div>}
                    </td>
                    <td className={`px-3 py-2 whitespace-nowrap ${enRetard ? "text-red-600 font-medium" : ""}`}>
                      {fmtJour(t[colonneDate])}{enRetard ? " (en retard)" : ""}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
