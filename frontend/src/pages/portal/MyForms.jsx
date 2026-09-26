/*
  « Mes formulaires » (espace client Albarka) — formulaires reçus du cabinet,
  à remplir ou déjà répondus. Écran fourni par le module commun forms-core.
*/
import React from "react";
import MyFormsCore from "@/components/forms-core/MyForms";

export default function MyForms() {
  return <MyFormsCore portalApiBase="/me/forms" />;
}
