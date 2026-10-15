import React from "react";
import PageJuridique, { CONTACT_JURIDIQUE } from "@/components/PageJuridique";

// Conditions de service du portail ALBARKA : page PUBLIQUE (sans connexion), adresse donnée à Meta et aux utilisateurs.
// À relire par le cabinet si le service évolue (règles d'accès, facturation, nouveaux canaux).
const DATE_MAJ = "15/10/2026";

// Contenu des sections : titre + `avant` (paragraphes), `puces` (liste) puis `apres` (paragraphes)
const SECTIONS = [
  {
    titre: "1. Objet",
    avant: [
      "Les présentes conditions encadrent l'utilisation du portail albarka-bf.com et des services associés (notifications par e-mail et par WhatsApp) " +
        "proposés par ALBARKA Consulting BF (« ALBARKA », « le cabinet »), cabinet comptable et fiscal établi à Ouagadougou, au Burkina Faso.",
      "En vous connectant au portail ou en échangeant avec le cabinet par WhatsApp, vous acceptez ces conditions.",
    ],
  },
  {
    titre: "2. Le service",
    avant: ["Le portail permet, selon les droits attribués à chaque compte :"],
    puces: [
      "de déposer et de consulter des documents ;",
      "de suivre les dossiers, les missions et les échéances ;",
      "de consulter et de régler des factures ;",
      "d'échanger avec le cabinet et de recevoir des notifications.",
    ],
    apres: ["Les missions comptables, fiscales ou sociales elles-mêmes restent régies par la lettre de mission ou le contrat signé avec le cabinet."],
  },
  {
    titre: "3. Compte et accès",
    puces: [
      "L'accès est réservé aux clients du cabinet et à ses collaborateurs. Les comptes sont créés ou validés par le cabinet.",
      "La connexion se fait par code à usage unique envoyé à l'adresse e-mail du compte : vous êtes responsable de la confidentialité de votre messagerie et de vos codes.",
      "Vous vous engagez à fournir des informations exactes et à nous signaler sans délai toute utilisation non autorisée de votre compte.",
      "Le cabinet peut suspendre ou fermer un compte en cas d'usage contraire à ces conditions, de risque pour la sécurité ou de fin de la relation.",
    ],
  },
  {
    titre: "4. Vos engagements",
    puces: [
      "Ne déposer que des documents dont vous avez le droit de disposer, exempts de virus et de contenu illicite.",
      "Ne pas tenter d'accéder aux données d'un autre client ni de perturber le fonctionnement du portail.",
      "Ne pas utiliser le service pour envoyer des messages abusifs, trompeurs ou non sollicités.",
    ],
  },
  {
    titre: "5. Messages WhatsApp et e-mails",
    avant: [
      "Le cabinet peut vous écrire par WhatsApp et par e-mail pour les besoins de votre dossier : demande de pièce, facture, échéance, rappel. " +
        "Les messages WhatsApp transitent par la plateforme WhatsApp Business de Meta, dont les conditions s'appliquent à cette partie du service.",
      "Vous pouvez à tout moment demander à ne plus recevoir de messages WhatsApp : répondez au cabinet ou écrivez-nous (voir section 10). " +
        "Les communications strictement nécessaires à l'exécution de votre mission restent possibles par d'autres moyens.",
    ],
  },
  {
    titre: "6. Données personnelles",
    avant: [
      "Le traitement de vos données est décrit dans notre politique de confidentialité, disponible à l'adresse albarka-bf.com/confidentialite. " +
        "Elle fait partie des présentes conditions.",
    ],
  },
  {
    titre: "7. Disponibilité et sécurité",
    avant: [
      "Nous nous efforçons de maintenir le portail accessible et sécurisé, mais nous ne pouvons pas garantir une disponibilité ininterrompue : " +
        "des interruptions peuvent survenir pour maintenance, mise à jour ou raison indépendante de notre volonté (réseau, prestataires). " +
        "Les échéances fiscales et légales de votre dossier ne doivent pas dépendre uniquement du portail : en cas de doute, contactez le cabinet.",
    ],
  },
  {
    titre: "8. Responsabilité",
    avant: [
      "Le portail est un outil d'échange et de suivi. Chaque partie reste responsable de l'exactitude des informations et documents qu'elle transmet. " +
        "Dans les limites permises par la loi, le cabinet n'est pas responsable des dommages indirects liés à l'indisponibilité du portail, " +
        "à un message non lu ou à un retard de transmission imputable à un tiers (opérateur, messagerie, WhatsApp).",
    ],
  },
  {
    titre: "9. Propriété intellectuelle",
    avant: [
      "Le portail, son contenu, ses marques et ses logos appartiennent au cabinet ou à ses prestataires. Les documents que vous déposez restent votre propriété ; " +
        "vous autorisez le cabinet à les traiter uniquement pour exécuter votre mission.",
    ],
  },
  {
    titre: "10. Contact, modification et droit applicable",
    avant: [
      "Pour toute question sur ces conditions, ou pour exercer vos droits, écrivez-nous à " + CONTACT_JURIDIQUE + " ou utilisez la page Contact du portail.",
      "Nous pouvons modifier ces conditions lorsque le service évolue ; la date de dernière mise à jour figure en haut de cette page. " +
        "L'utilisation du portail après modification vaut acceptation.",
      "Les présentes conditions sont régies par le droit du Burkina Faso. En cas de litige, les parties recherchent d'abord une solution amiable.",
    ],
  },
];

export default function Conditions() {
  return (
    <PageJuridique
      kicker="Conditions"
      titre="Conditions de"
      titreAccent="service"
      dateMaj={DATE_MAJ}
      sections={SECTIONS}
      testId="page-conditions"
    />
  );
}
