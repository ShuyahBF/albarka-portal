import { DOMAINES, elementsDuDomaine } from "./domainesClient";

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
