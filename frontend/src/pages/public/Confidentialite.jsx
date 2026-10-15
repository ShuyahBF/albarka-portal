import React from "react";
import PublicLayout from "@/components/PublicLayout";

// Politique de confidentialité d'ALBARKA : page PUBLIQUE (sans connexion), adresse à donner à Meta et aux utilisateurs.
// Chaque section décrit une réalité du portail (comptes, pièces, WhatsApp, e-mails) — à relire par le cabinet si le service évolue.
const DATE_MAJ = "15/10/2026";

// Contenu des sections : titre + `avant` (paragraphes), `puces` (liste) puis `apres` (paragraphes)
const SECTIONS = [
  {
    titre: "1. Qui sommes-nous ?",
    avant: [
      "ALBARKA Consulting BF (« ALBARKA », « le cabinet ») est un cabinet comptable et fiscal établi à Ouagadougou, au Burkina Faso. " +
        "Le portail albarka-bf.com permet à ses clients et à ses collaborateurs d'échanger des documents, de suivre leurs dossiers, " +
        "leurs échéances et leurs factures, et de recevoir des notifications.",
      "ALBARKA est responsable du traitement des données personnelles décrites ci-dessous.",
    ],
  },
  {
    titre: "2. Quelles données collectons-nous ?",
    puces: [
      "Identité et coordonnées : nom, adresse e-mail, numéro de téléphone et de WhatsApp, société représentée.",
      "Connexion : adresse e-mail, codes de connexion à usage unique (OTP), date et heure des connexions, adresse IP.",
      "Documents que vous déposez ou que le cabinet vous remet : pièces comptables et fiscales, factures, contrats, bulletins de paie, courriers.",
      "Messages échangés avec le cabinet, y compris par WhatsApp (contenu des messages, numéro de l'expéditeur, date, état de livraison).",
      "Données d'usage minimales : pages consultées sur le portail, journal d'activité nécessaire à la sécurité.",
    ],
  },
  {
    titre: "3. Pourquoi utilisons-nous ces données ?",
    puces: [
      "Exécuter les missions que vous confiez au cabinet (comptabilité, fiscalité, paie, secrétariat).",
      "Vous permettre de vous connecter de façon sécurisée et d'accéder à vos documents.",
      "Vous envoyer des notifications utiles : dépôt d'une pièce, facture, échéance, rappel (par e-mail ou par WhatsApp).",
      "Répondre à vos demandes reçues sur le portail ou par WhatsApp.",
      "Assurer la sécurité du service, prévenir les abus et respecter nos obligations légales (comptables, fiscales).",
    ],
    apres: [
      "Nous ne vendons pas vos données et nous ne les utilisons pas à des fins publicitaires.",
    ],
  },
  {
    titre: "4. WhatsApp",
    avant: [
      "Le cabinet utilise l'API WhatsApp Business de Meta pour vous écrire et pour recevoir vos messages. Nous n'écrivons à un numéro " +
        "que s'il s'agit d'un client ou d'un correspondant du cabinet, ou à sa demande. Vos messages WhatsApp transitent par les serveurs de Meta, " +
        "dont la propre politique de confidentialité s'applique à cette partie du service.",
      "Vous pouvez demander à ne plus recevoir de messages WhatsApp à tout moment, en répondant au cabinet ou en nous contactant (voir section 9).",
    ],
  },
  {
    titre: "5. Qui reçoit vos données ?",
    avant: [
      "Vos données sont accessibles uniquement aux collaborateurs du cabinet qui en ont besoin pour traiter votre dossier, selon leurs droits sur le portail. " +
        "Pour faire fonctionner le service, nous faisons appel à des prestataires techniques qui les traitent pour notre compte :",
    ],
    puces: [
      "hébergement du site et de la base de données (serveurs situés en Europe) ;",
      "stockage des documents ;",
      "envoi d'e-mails ;",
      "messagerie WhatsApp (Meta Platforms) ;",
      "outils d'analyse automatique de documents, utilisés pour aider les collaborateurs à lire les pièces que vous déposez.",
    ],
  },
  {
    titre: "6. Combien de temps les conservons-nous ?",
    avant: [
      "Nous conservons vos données tant que dure notre relation, puis pendant les délais exigés par la loi, notamment pour les documents comptables et fiscaux. " +
        "À l'expiration de ces délais, elles sont supprimées ou rendues anonymes.",
    ],
  },
  {
    titre: "7. Comment protégeons-nous vos données ?",
    puces: [
      "Connexion sécurisée (HTTPS) et code de connexion à usage unique envoyé à votre adresse e-mail.",
      "Droits d'accès par rôle : chaque collaborateur ne voit que ce que sa fonction exige.",
      "Journal des actions sensibles et contrôle des téléchargements.",
      "Aucun mot de passe, clé ou secret n'est affiché ou transmis dans les messages.",
    ],
  },
  {
    titre: "8. Cookies et stockage du navigateur",
    avant: [
      "Le portail enregistre dans votre navigateur uniquement ce qui est nécessaire à son fonctionnement (session de connexion, préférences d'affichage). " +
        "Nous n'utilisons pas de cookies publicitaires.",
    ],
  },
  {
    titre: "9. Vos droits et comment les exercer",
    avant: [
      "Conformément à la réglementation applicable au Burkina Faso en matière de protection des données personnelles, vous avez le droit d'accéder à vos données, " +
        "de les faire rectifier, de vous opposer à leur traitement ou d'en demander la suppression, dans la limite de nos obligations légales de conservation.",
      "Pour exercer ces droits, ou pour demander la suppression de vos données, écrivez-nous à contact@albarka-bf.com ou utilisez la page Contact du portail. " +
        "Nous vous répondons dans un délai raisonnable. Si vous estimez que vos droits ne sont pas respectés, vous pouvez saisir l'autorité burkinabè de protection des données personnelles.",
    ],
  },
  {
    titre: "10. Modifications de cette politique",
    avant: [
      "Nous pouvons mettre à jour cette politique lorsque le service évolue. La date de dernière mise à jour figure en haut de cette page.",
    ],
  },
];

export default function Confidentialite() {
  return (
    <PublicLayout>
      <section className="py-16 bg-[var(--albarka-paper)]">
        <div className="max-w-3xl mx-auto px-6" data-testid="page-confidentialite">
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-3">Confidentialité</div>
          <h1 className="font-display text-4xl md:text-5xl text-foreground mb-3">
            Politique de <span className="albarka-underline">confidentialité</span>
          </h1>
          <p className="text-sm text-muted-foreground mb-10">
            ALBARKA Consulting BF · albarka-bf.com · Dernière mise à jour : {DATE_MAJ}
          </p>

          <div className="space-y-8">
            {SECTIONS.map((s) => (
              <div key={s.titre} className="albarka-card p-6 space-y-3">
                <h2 className="text-lg font-semibold text-[#0F6B4A]">{s.titre}</h2>
                {(s.avant || []).map((p) => (
                  <p key={p} className="text-sm leading-relaxed text-foreground/90">{p}</p>
                ))}
                {s.puces && (
                  <ul className="list-disc pl-5 space-y-1.5 text-sm leading-relaxed text-foreground/90">
                    {s.puces.map((p) => <li key={p}>{p}</li>)}
                  </ul>
                )}
                {(s.apres || []).map((p) => (
                  <p key={p} className="text-sm leading-relaxed text-foreground/90">{p}</p>
                ))}
              </div>
            ))}
          </div>
        </div>
      </section>
    </PublicLayout>
  );
}
