/*
  Page publique de remplissage d'un formulaire : /f/<jeton>.
  Ouverte depuis le lien reçu par e-mail/WhatsApp (client invité) ou depuis
  le lien public partagé (non-client). Aucune connexion n'est demandée.
  Écran fourni par le module commun forms-core.
*/
import React from "react";
import { useParams } from "react-router-dom";
import PublicFormPage from "@/components/forms-core/PublicFormPage";

export default function FillForm() {
  const { token: brut } = useParams(); // jeton du lien (personnel ou public)
  // Lien copié depuis une messagerie : on retire les caractères invisibles (espace de largeur nulle, espaces…) qui le cassent
  const token = (brut || "").replace(/[\u200B-\u200F\u2028-\u202F\u2060\uFEFF\u00AD\s]/g, "");
  return <PublicFormPage publicApiBase="/public/forms" token={token} brand={{ name: "ALBARKA Consulting BF" }} />;
}
