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
  const { token } = useParams(); // jeton du lien (personnel ou public)
  return <PublicFormPage publicApiBase="/public/forms" token={token} brand={{ name: "ALBARKA Consulting BF" }} />;
}
