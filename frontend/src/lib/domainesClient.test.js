import { DOMAINES, elementsDuDomaine, etatDeclarations } from "./domainesClient";

test("chaque élément est rangé dans le bon domaine", () => {
  const donnees = {
    missions: [{ id: 1, type: "tenue_comptable" }, { id: 2, type: "declaration_fiscale" }, { id: 3, type: "paie_rh" }, { id: 4, type: "conseil" }],
    echeances: [{ id: 1, type: "tva" }, { id: 2, type: "cnss" }, { id: 3, type: "bilan_annuel" }, { id: 4, type: "autre" }],
    documents: [{ id: 1, theme: "comptable" }, { id: 2, category: "declaration" }, { id: 3, theme: "cnss" }, { id: 4, category: "facture" }, { id: 5, category: "courrier" }],
  };
  const c = elementsDuDomaine("comptabilite", donnees), f = elementsDuDomaine("fiscalite", donnees), r = elementsDuDomaine("rh", donnees);
  expect(c.missions.map((m) => m.id)).toEqual([1]);
  expect(f.missions.map((m) => m.id)).toEqual([2]);
  expect(r.missions.map((m) => m.id)).toEqual([3]);                       // « conseil » n'appartient à aucun domaine
  expect(c.echeances.map((e) => e.id)).toEqual([3]);
  expect(f.echeances.map((e) => e.id)).toEqual([1]);
  expect(r.echeances.map((e) => e.id)).toEqual([2]);
  expect(c.documents.map((x) => x.id)).toEqual([1, 4]);
  expect(f.documents.map((x) => x.id)).toEqual([2]);
  expect(r.documents.map((x) => x.id)).toEqual([3]);
});

test("domaine inconnu ou listes absentes : rien, sans erreur", () => {
  expect(elementsDuDomaine("autre", {})).toEqual({ missions: [], echeances: [], documents: [] });
  expect(elementsDuDomaine("rh")).toEqual({ missions: [], echeances: [], documents: [] });
  expect(Object.keys(DOMAINES)).toEqual(["comptabilite", "fiscalite", "rh"]);
});

test("déclarations du mois : déposée, à faire, en retard ; retards de tous les mois", () => {
  const e = [
    { id: 1, type: "tva", due_date: "2026-10-15", status: "traitee" },          // déposée
    { id: 2, type: "irpp", due_date: "2026-10-20", status: "a_venir" },         // en retard (date dépassée au 26/10)
    { id: 3, type: "is", due_date: "2026-10-31", status: "en_cours" },          // à faire
    { id: 4, type: "tva", due_date: "2026-09-15", status: "en_retard" },        // retard d'un mois précédent
    { id: 5, type: "tva", due_date: "2026-09-10", status: "traitee" },          // déposée, mois précédent : ignorée
    { id: 6, type: "cnss", due_date: "2026-10-15", status: "a_venir" },         // pas fiscale (RH)
  ];
  const r = etatDeclarations(e, "2026-10-26");
  expect(r.mois.map((x) => [x.id, x.etat])).toEqual([[1, "deposee"], [2, "en_retard"], [3, "a_faire"]]);
  expect(r.decomptes).toEqual({ deposee: 1, a_faire: 1, en_retard: 1 });
  expect(r.retards.map((x) => [x.id, x.jours])).toEqual([[4, 41], [2, 6]]);
  expect(etatDeclarations([], "2026-10-26")).toEqual({ mois: [], decomptes: { deposee: 0, a_faire: 0, en_retard: 0 }, retards: [] });
});
