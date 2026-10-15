import React from "react";
import PageJuridique, { CONTACT_JURIDIQUE } from "@/components/PageJuridique";

// Instructions de suppression des données : page PUBLIQUE (sans connexion), adresse demandée par Meta
// (« URL des instructions de suppression des données ») pour l'application ALBARKA.
const DATE_MAJ = "15/10/2026";

// Contenu des sections : titre + `avant` (paragraphes), `puces` (liste) puis `apres` (paragraphes)
const SECTIONS = [
  {
    titre: "1. À qui s'adresse cette page ?",
    avant: [
      "Cette page explique comment demander la suppression des données personnelles que ALBARKA Consulting BF détient sur vous : " +
        "compte du portail albarka-bf.com, documents déposés, messages échangés avec le cabinet (y compris par WhatsApp), coordonnées.",
    ],
  },
  {
    titre: "2. Comment demander la suppression",
    avant: ["Envoyez votre demande par l'un de ces moyens :"],
    puces: [
      "par e-mail à " + CONTACT_JURIDIQUE + ", avec pour objet « Suppression de mes données » ;",
      "depuis la page Contact du portail albarka-bf.com/contact ;",
      "par WhatsApp, en écrivant « Suppression de mes données » à la conversation du cabinet depuis le numéro concerné.",
    ],
    apres: [
      "Indiquez votre nom, l'adresse e-mail ou le numéro de téléphone/WhatsApp utilisé avec ALBARKA, et la société concernée s'il y en a une. " +
        "Ces éléments nous permettent de retrouver vos données.",
    ],
  },
  {
    titre: "3. Vérification de votre identité",
    avant: [
      "Pour protéger vos données, nous vérifions que la demande vient bien de vous : nous pouvons vous répondre à l'adresse e-mail ou au numéro concerné " +
        "et vous demander une confirmation avant de supprimer quoi que ce soit.",
    ],
  },
  {
    titre: "4. Ce qui est supprimé",
    puces: [
      "votre compte du portail et vos accès ;",
      "vos coordonnées (e-mail, téléphone, numéro WhatsApp) ;",
      "l'historique des messages échangés avec le cabinet, y compris WhatsApp ;",
      "les documents et pièces que vous avez déposés, lorsque la loi ne nous impose pas de les conserver.",
    ],
  },
  {
    titre: "5. Ce que nous pouvons devoir conserver",
    avant: [
      "Certaines données doivent être conservées pendant les délais prévus par la loi, notamment les documents comptables, fiscaux et de facturation, " +
        "ou si elles sont nécessaires pour défendre un droit. Dans ce cas, nous vous l'indiquons, nous les conservons uniquement pour cet usage et " +
        "nous les supprimons à l'issue du délai.",
    ],
  },
  {
    titre: "6. Délai de traitement",
    avant: [
      "Nous accusons réception de votre demande et la traitons dans un délai raisonnable. Vous recevez une confirmation lorsque la suppression est effectuée.",
    ],
  },
  {
    titre: "7. Messages WhatsApp",
    avant: [
      "Si vous souhaitez seulement ne plus recevoir de messages WhatsApp du cabinet, sans supprimer votre compte, répondez-nous en ce sens ou écrivez à " +
        CONTACT_JURIDIQUE + " : nous le noterons sur votre fiche.",
      "Les messages stockés par Meta sur WhatsApp relèvent de Meta : vous pouvez les supprimer depuis votre propre application WhatsApp et consulter la politique de Meta.",
    ],
  },
];

export default function SuppressionDonnees() {
  return (
    <PageJuridique
      kicker="Vos données"
      titre="Suppression de"
      titreAccent="vos données"
      dateMaj={DATE_MAJ}
      sections={SECTIONS}
      testId="page-suppression-donnees"
    />
  );
}
