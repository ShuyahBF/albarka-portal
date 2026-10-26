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

/*
  Lot 76 — Page Fiscalité du client : état des déclarations du MOIS et retards, d'après les échéances fiscales (TVA, IS, IRPP, déclaration annuelle).
  - « Déposée »  : l'échéance est marquée « traitée » par le cabinet ;
  - « En retard » : date dépassée et pas traitée (ou marquée « en retard ») ; `jours` = nombre de jours de retard ;
  - « À faire »  : pas encore traitée, date non dépassée.
  `aujourdhui` = « AAAA-MM-JJ ». Renvoie { mois, decomptes, retards } : `mois` = échéances fiscales du mois en cours (triées par date),
  `retards` = toutes les échéances fiscales en retard, de n'importe quel mois (les plus anciennes d'abord).
*/
export function etatDeclarations(echeances = [], aujourdhui) {
  const types = DOMAINES.fiscalite.echeances;
  const t0 = new Date(`${aujourdhui}T12:00:00Z`).getTime();
  const evaluer = (e) => {
    const jours = Math.floor((t0 - new Date(`${String(e.due_date).slice(0, 10)}T12:00:00Z`).getTime()) / 86400000);
    const etat = e.status === "traitee" ? "deposee" : (e.status === "en_retard" || jours > 0 ? "en_retard" : "a_faire");
    return { ...e, etat, jours: etat === "en_retard" ? Math.max(jours, 1) : 0 };
  };
  const fiscales = echeances.filter((e) => types.includes(e.type) && e.due_date).map(evaluer);
  const mois = fiscales.filter((e) => String(e.due_date).slice(0, 7) === aujourdhui.slice(0, 7)).sort((a, b) => String(a.due_date).localeCompare(String(b.due_date)));
  const retards = fiscales.filter((e) => e.etat === "en_retard").sort((a, b) => String(a.due_date).localeCompare(String(b.due_date)));
  const decomptes = { deposee: 0, a_faire: 0, en_retard: 0 };
  mois.forEach((e) => { decomptes[e.etat] += 1; });
  return { mois, decomptes, retards };
}

export const STATUTS_MISSION = { en_attente: "En attente", en_cours: "En cours", en_revue: "En revue", terminee: "Terminée", archivee: "Archivée" };
export const STATUTS_ECHEANCE = { a_venir: "À venir", en_cours: "En cours", traitee: "Traitée", en_retard: "En retard" };
