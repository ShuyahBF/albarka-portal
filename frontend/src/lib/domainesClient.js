/*
  Lot 72 — Espace client : rangement des éléments d'un client par DOMAINE (Comptabilité, Fiscalité, Ressources humaines).
  Source UNIQUE des correspondances entre les domaines et :
    - les types de missions du cabinet (MISSION_TYPES côté serveur),
    - les types d'échéances (ECHEANCE_TYPES côté serveur),
    - les documents que le cabinet a mis à disposition (« thème » de classement et catégorie de document).
  Fonctions pures, testées dans domainesClient.test.js.
*/
export const DOMAINES = {
  comptabilite: {
    titre: "Comptabilité", missions: ["tenue_comptable", "audit"], echeances: ["bilan_annuel"],
    themes: ["comptable"], categories: ["facture", "proforma", "recu"],   // les déclarations déposées ont leur propre section (page Comptabilité)
    vide: "Aucun élément de comptabilité pour l'instant.",
  },
  fiscalite: {
    titre: "Fiscalité", missions: ["declaration_fiscale"], echeances: ["tva", "is", "irpp", "declaration_annuelle"],
    themes: ["fiscal"], categories: ["declaration"],
    vide: "Aucun élément de fiscalité pour l'instant.",
  },
  rh: {
    titre: "Ressources humaines", missions: ["paie_rh"], echeances: ["cnss", "iuts"],
    themes: ["rh", "cnss"], categories: [],
    vide: "Aucun élément de ressources humaines pour l'instant.",
  },
};

/** Éléments d'un client rangés dans un domaine : { missions, echeances, documents } (listes vides si le domaine est inconnu). */
export function elementsDuDomaine(cle, { missions = [], echeances = [], documents = [] } = {}) {
  const d = DOMAINES[cle];
  if (!d) return { missions: [], echeances: [], documents: [] };
  return {
    missions: missions.filter((m) => d.missions.includes(m.type)),
    echeances: echeances.filter((e) => d.echeances.includes(e.type)),
    documents: documents.filter((x) => d.themes.includes(x.theme) || d.categories.includes(x.category)),
  };
}

export const STATUTS_MISSION = { en_attente: "En attente", en_cours: "En cours", en_revue: "En revue", terminee: "Terminée", archivee: "Archivée" };
export const STATUTS_ECHEANCE = { a_venir: "À venir", en_cours: "En cours", traitee: "Traitée", en_retard: "En retard" };
