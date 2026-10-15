/*
  Formulaires (Albarka) — pages d'administration.
  Simple branchement des écrans du module commun forms-core
  (components/forms-core, NE PAS MODIFIER là-bas) sur les routes Albarka :
    /admin/forms       → bibliothèque (créer, catégories, archiver…)
    /admin/forms/:id   → constructeur · envoi & suivi · réponses · statistiques
  Accès : rôle « formulaires » (ou superviseur), contrôlé aussi côté serveur.
*/
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { apiClient } from "@/lib/api";
import FormsLibrary from "@/components/forms-core/FormsLibrary";
import FormDetail from "@/components/forms-core/FormDetail";

// Réglages communs aux deux pages : adresse de l'API, chemin des pages,
// chemin du lien public de remplissage et couleur principale Albarka.
const FORMS_PROPS = { apiBase: "/forms", basePath: "/admin/forms" };

/*
  Modèles prêts à l'emploi (ex. « Vérification de la paie — Burkina Faso »).
  Un clic : on lit le modèle (GET /forms-modeles/{code}), on crée le formulaire avec le
  constructeur habituel (POST /forms), on ACTIVE son lien public (sans connexion), puis on
  ouvre la page du formulaire où se trouvent le lien à copier, le QR code et les réponses.
*/
function ModelesFormulaires() {
  const navigate = useNavigate();
  const [modeles, setModeles] = useState([]);
  const [busy, setBusy] = useState("");

  // Liste des modèles proposés (silencieux si l'utilisateur n'y a pas droit)
  useEffect(() => {
    apiClient.get("/forms-modeles").then((r) => setModeles(r.data.modeles || [])).catch(() => setModeles([]));
  }, []);

  const creer = async (code) => {
    setBusy(code);
    try {
      const { data: modele } = await apiClient.get(`/forms-modeles/${code}`);
      const { data: form } = await apiClient.post("/forms", modele);
      await apiClient.post(`/forms/${form.id}/public-link`, { enabled: true });
      toast.success("Formulaire créé, lien public activé.");
      navigate(`/admin/forms/${form.id}`);
    } catch (e) {
      // 409 = un formulaire du même titre existe déjà : on l'explique clairement
      const detail = e?.response?.data?.detail;
      toast.error(e?.response?.status === 409 ? "Ce formulaire existe déjà : ouvrez-le dans la liste ci-dessous."
        : (typeof detail === "string" ? detail : "Création impossible."));
    } finally { setBusy(""); }
  };

  if (!modeles.length) return null;
  return (
    <div className="mb-6 rounded-lg border border-emerald-200 bg-emerald-50/60 p-4" data-testid="forms-modeles">
      <h2 className="mb-1 text-base font-semibold">Modèles prêts à l'emploi</h2>
      <p className="mb-3 text-sm text-slate-600">Créez un formulaire complet en un clic, puis partagez son lien public.</p>
      <div className="flex flex-col gap-3">
        {modeles.map((m) => (
          <div key={m.code} className="flex flex-wrap items-center justify-between gap-3 rounded-md border bg-white p-3">
            <div className="min-w-0">
              <div className="font-medium">{m.title}</div>
              <div className="text-sm text-slate-600">{m.description} ({m.questions} champs)</div>
            </div>
            <button type="button" disabled={busy === m.code} onClick={() => creer(m.code)}
              className="rounded-md bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-800 disabled:opacity-60"
              data-testid={`forms-modele-${m.code}`}>
              {busy === m.code ? "Patientez…" : "Créer ce formulaire"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function AdminFormsLibrary() {
  return (
    <>
      <ModelesFormulaires />
      <FormsLibrary {...FORMS_PROPS} />
    </>
  );
}

export function AdminFormDetail() {
  const { id } = useParams(); // identifiant du formulaire dans l'adresse
  return <FormDetail {...FORMS_PROPS} formId={id} publicPath="/f" color="#0F6B4A" />;
}
