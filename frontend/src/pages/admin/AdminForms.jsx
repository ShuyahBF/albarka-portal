/*
  Formulaires (Albarka) — pages d'administration.
  Simple branchement des écrans du module commun forms-core
  (components/forms-core, NE PAS MODIFIER là-bas) sur les routes Albarka :
    /admin/forms       → bibliothèque (créer, catégories, archiver…)
    /admin/forms/:id   → constructeur · envoi & suivi · réponses · statistiques
  Accès : rôle « formulaires » (ou superviseur), contrôlé aussi côté serveur.
*/
import React from "react";
import { useParams } from "react-router-dom";
import FormsLibrary from "@/components/forms-core/FormsLibrary";
import FormDetail from "@/components/forms-core/FormDetail";

// Réglages communs aux deux pages : adresse de l'API, chemin des pages,
// chemin du lien public de remplissage et couleur principale Albarka.
const FORMS_PROPS = { apiBase: "/forms", basePath: "/admin/forms" };

export function AdminFormsLibrary() {
  return <FormsLibrary {...FORMS_PROPS} />;
}

export function AdminFormDetail() {
  const { id } = useParams(); // identifiant du formulaire dans l'adresse
  return <FormDetail {...FORMS_PROPS} formId={id} publicPath="/f" color="#0F6B4A" />;
}
