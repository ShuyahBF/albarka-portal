// ChampsNom.jsx — remplace le champ unique « Nom complet » par DEUX champs (règle du 14/11/2026) :
//   - NOM de famille : écrit en MAJUSCULES ;
//   - Prénoms : 1re lettre de chaque mot en majuscule.
// Le Nom complet (concaténation) est montré en aperçu sous les champs. La correction d'orthographe est
// appliquée en quittant le champ (et de nouveau par le serveur à l'enregistrement).
import React from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formaterNom, formaterPrenoms, assemblerNom } from "@/lib/noms";

/**
 * form / setForm : état du formulaire de la page (doit contenir `nom` et `prenoms`).
 * testid : préfixe des data-testid (ex. "client" -> client-nom-input, client-prenoms-input).
 */
export default function ChampsNom({ form, setForm, testid = "nom" }) {
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <Label>NOM de famille</Label>
          <Input
            value={form.nom || ""}
            placeholder="BADINI"
            onChange={(e) => setForm({ ...form, nom: e.target.value })}
            onBlur={() => setForm((f) => ({ ...f, nom: formaterNom(f.nom) }))}
            data-testid={`${testid}-nom-input`}
          />
        </div>
        <div>
          <Label>Prénoms</Label>
          <Input
            value={form.prenoms || ""}
            placeholder="Awa"
            onChange={(e) => setForm({ ...form, prenoms: e.target.value })}
            onBlur={() => setForm((f) => ({ ...f, prenoms: formaterPrenoms(f.prenoms) }))}
            data-testid={`${testid}-prenoms-input`}
          />
        </div>
      </div>
      <p className="text-xs text-slate-500">
        Nom complet : <b className="text-slate-700">{assemblerNom(form.nom, form.prenoms) || "—"}</b>
      </p>
    </div>
  );
}
