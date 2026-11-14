// ChampsNom.jsx — remplace le champ unique « Nom complet » (règles du 14/11/2026) :
//   - Titre : liste déroulante (Mr, Mme, Mlle, Dr, Pr, Sr…) + « Autre… » pour une saisie libre ;
//   - NOM de famille : écrit en MAJUSCULES ;
//   - Prénoms : 1re lettre de chaque mot en majuscule ;
//   - pictogramme ⇄ entre NOM et Prénoms : inverse les deux en cas d'erreur de saisie ;
//   - pictogramme « Enregistrer » après Prénoms (fiche existante seulement) : enregistre la correction du nom
//     (actif seulement si modifié, avec la mention « modifié, non enregistré » — règle 15).
// Le Nom complet (Titre + NOM + Prénoms) est montré en aperçu. Le serveur corrige aussi à l'enregistrement.
import React, { useRef, useState } from "react";
import { ArrowLeftRight, Save, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TITRES, formaterNom, formaterPrenoms, formaterTitre, assemblerNom } from "@/lib/noms";

/**
 * form / setForm : état du formulaire de la page (champs `titre`, `nom`, `prenoms`).
 * testid : préfixe des data-testid.
 * onSave : (facultatif) async ({titre, nom, prenoms}) => enregistre la correction ; absent à la création.
 */
export default function ChampsNom({ form, setForm, testid = "nom", onSave }) {
  const courant = { titre: form.titre || "", nom: form.nom || "", prenoms: form.prenoms || "" };
  // Valeurs enregistrées de référence (celles de l'ouverture de la fiche), pour détecter « modifié, non enregistré »
  const reference = useRef(courant);
  const [enCours, setEnCours] = useState(false);
  const [autre, setAutre] = useState(!!courant.titre && !TITRES.includes(formaterTitre(courant.titre)));
  const modifie = ["titre", "nom", "prenoms"].some((k) => courant[k] !== reference.current[k]);

  const maj = (champs) => setForm((f) => ({ ...f, ...champs }));
  const inverser = () => maj({ nom: formaterNom(courant.prenoms), prenoms: formaterPrenoms(courant.nom) });

  const enregistrer = async () => {
    const valeurs = { titre: formaterTitre(courant.titre), nom: formaterNom(courant.nom), prenoms: formaterPrenoms(courant.prenoms) };
    if (!valeurs.nom && !valeurs.prenoms) { toast.error("Nom requis"); return; }
    setEnCours(true);
    toast.info("Enregistrement du nom en cours…");
    try {
      await onSave(valeurs);
      maj(valeurs);
      reference.current = valeurs;
      toast.success(`Nom enregistré : ${assemblerNom(valeurs.nom, valeurs.prenoms, valeurs.titre)}`);
    } catch (e) {
      toast.error("Le nom n'a pas pu être enregistré");
    } finally { setEnCours(false); }
  };

  return (
    <div className="space-y-2">
      <div>
        <Label>Titre</Label>
        <select
          className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
          value={autre ? "__autre__" : (courant.titre || "")}
          onChange={(e) => {
            if (e.target.value === "__autre__") { setAutre(true); maj({ titre: "" }); }
            else { setAutre(false); maj({ titre: e.target.value }); }
          }}
          data-testid={`${testid}-titre-select`}
        >
          <option value="">— Aucun —</option>
          {TITRES.map((t) => <option key={t} value={t}>{t}</option>)}
          <option value="__autre__">Autre…</option>
        </select>
        {autre && (
          <Input className="mt-1" placeholder="Titre (ex. Son Excellence)" value={courant.titre}
                 onChange={(e) => maj({ titre: e.target.value })} data-testid={`${testid}-titre-libre`} />
        )}
      </div>
      {/* NOM  ⇄  Prénoms  [Enregistrer] */}
      <div className="flex items-end gap-2">
        <div className="flex-1 min-w-0">
          <Label>NOM de famille</Label>
          <Input value={courant.nom} placeholder="BADINI"
                 onChange={(e) => maj({ nom: e.target.value })}
                 onBlur={() => maj({ nom: formaterNom(courant.nom) })}
                 data-testid={`${testid}-nom-input`} />
        </div>
        <button type="button" onClick={inverser} title="Inverser NOM et Prénoms" aria-label="Inverser NOM et Prénoms"
                className="h-9 w-9 shrink-0 rounded-md border border-sky-300 text-sky-700 hover:bg-sky-50 flex items-center justify-center"
                data-testid={`${testid}-inverser`}>
          <ArrowLeftRight size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <Label>Prénoms</Label>
          <Input value={courant.prenoms} placeholder="Awa"
                 onChange={(e) => maj({ prenoms: e.target.value })}
                 onBlur={() => maj({ prenoms: formaterPrenoms(courant.prenoms) })}
                 data-testid={`${testid}-prenoms-input`} />
        </div>
        {onSave && (
          <button type="button" onClick={enregistrer} disabled={!modifie || enCours}
                  title="Enregistrer la correction du nom" aria-label="Enregistrer la correction du nom"
                  className="h-9 w-9 shrink-0 rounded-md bg-emerald-600 text-white disabled:opacity-40 flex items-center justify-center"
                  data-testid={`${testid}-enregistrer-nom`}>
            {enCours ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
          </button>
        )}
      </div>
      <p className="text-xs text-slate-500">
        Nom complet : <b className="text-slate-700">{assemblerNom(courant.nom, courant.prenoms, courant.titre) || "—"}</b>
        {onSave && modifie && <span className="ml-2 text-amber-700">· modifié, non enregistré</span>}
      </p>
    </div>
  );
}
