/** @jest-environment jsdom */
// Lot 86 — bloc « Mes tâches » : replié à l'origine, saisie par Entrée, texte libre + liste à cocher (comme SAWALI), vue Direction.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPatch = jest.fn();
const mockPut = jest.fn();
jest.mock("@/lib/api", () => ({ apiClient: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a), put: (...a) => mockPut(...a), patch: (...a) => mockPatch(...a), delete: jest.fn() }, extractError: () => "erreur" }), { virtual: true });
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }), { virtual: true });
// L'alias « @/ » n'existe pas sous Jest : doublures simples des composants d'interface
jest.mock("@/components/ui/button", () => ({ Button: (p) => <button {...p} /> }), { virtual: true });
jest.mock("@/components/ui/input", () => ({ Input: (p) => <input {...p} /> }), { virtual: true });
jest.mock("@/components/ui/label", () => ({ Label: (p) => <label {...p} /> }), { virtual: true });
jest.mock("@/components/ui/textarea", () => ({ Textarea: (p) => <textarea {...p} /> }), { virtual: true });
jest.mock("@/components/ui/switch", () => ({ Switch: ({ checked, onCheckedChange, ...r }) => <input type="checkbox" checked={checked} onChange={(e) => onCheckedChange(e.target.checked)} {...r} /> }), { virtual: true });

import TachesPersonnel from "./TachesPersonnel";

const attendre = () => act(() => new Promise((r) => setTimeout(r, 20)));
const TACHES = [
  { id: "t1", titre: "Déclarer la TVA", details: "", echeance: "2026-11-15", statut: "a_faire", realisee_le: null, elements: [] },
  { id: "t2", titre: "Clôture", details: "", echeance: null, statut: "a_faire", realisee_le: null,
    elements: [{ id: "e1", texte: "Relever les banques", fait: true, fait_le: "2026-11-02T08:00:00Z", ordre: 0 }, { id: "e2", texte: "Lettrage", fait: false, fait_le: null, ordre: 1 }] },
];

function monter(user) {
  const div = document.createElement("div");
  document.body.appendChild(div);
  const racine = createRoot(div);
  act(() => racine.render(<TachesPersonnel user={user} />));
  return div;
}
// Saisie dans un champ React contrôlé, puis touche Entrée
function saisir(el, valeur) {
  const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  act(() => { Object.getOwnPropertyDescriptor(proto, "value").set.call(el, valeur); el.dispatchEvent(new Event("input", { bubbles: true })); });
}
const entree = (el) => act(() => { el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
const q = (div, id) => div.querySelector(`[data-testid="${id}"]`);

beforeEach(() => {
  [mockGet, mockPost, mockPatch, mockPut].forEach((m) => m.mockReset());
  mockPost.mockResolvedValue({ data: {} });
  mockGet.mockImplementation((url) => {
    if (url === "/me/taches") return Promise.resolve({ data: TACHES });
    if (url === "/me/taches/rappel") return Promise.resolve({ data: { actif: false, heure: "08:00" } });
    if (url === "/me/taches/personnel") return Promise.resolve({ data: [{ id: "a1", full_name: "Awa", a_faire: 1, faites: 2 }] });
    if (url === "/me/taches/personnel/a1") return Promise.resolve({ data: { membre: { id: "a1" }, taches: [
      ...TACHES, { id: "t3", titre: "Payer la CNSS", statut: "fait", realisee_le: "2026-11-05T09:00:00+00:00", elements: [] }] } });
    return Promise.reject(new Error(url));
  });
});

async function ouvrir(user) {
  const div = monter(user);
  act(() => q(div, "taches-entete").click());
  await attendre();
  return div;
}

test("le bloc est replié à l'origine et ne charge rien avant l'ouverture", async () => {
  const div = monter({ roles: ["comptable"] });
  expect(q(div, "taches-contenu")).toBeNull();
  expect(mockGet).not.toHaveBeenCalled();
  act(() => q(div, "taches-entete").click());
  await attendre();
  expect(div.textContent).toContain("Déclarer la TVA");
  expect(div.textContent).toContain("15/11/2026");
  expect(q(div, "taches-onglet-personnel")).toBeNull();       // pas d'onglet « personnel » pour un comptable
});

test("les deux formats : texte libre et liste à cocher avec décompte, éléments faits barrés", async () => {
  const div = await ouvrir({ roles: ["comptable"] });
  expect(q(div, "tache-t1").querySelector('[data-testid="liste-a-cocher"]')).toBeNull();     // texte libre : simple case à cocher
  expect(q(div, "tache-cocher-t1")).not.toBeNull();
  const liste = q(div, "tache-t2").querySelector('[data-testid="liste-a-cocher"]');
  expect(liste.textContent).toContain("1 fait(s) / 2");
  expect(q(div, "element-e1").querySelector("input[type=checkbox]").checked).toBe(true);
  expect(q(div, "tache-t2").className).toContain("border-blue-600");                          // cadre mince et bleu
});

test("Entrée dans le titre enregistre la tâche (texte libre), sans bouton", async () => {
  const div = await ouvrir({ roles: ["comptable"] });
  saisir(q(div, "taches-titre"), "Appeler le client");
  entree(q(div, "taches-titre"));
  await attendre();
  expect(mockPost).toHaveBeenCalledWith("/me/taches", { titre: "Appeler le client", details: "", echeance: null, elements: [] });
});

test("liste à cocher : Entrée ajoute un élément, Entrée sur une ligne vide enregistre la tâche", async () => {
  const div = await ouvrir({ roles: ["comptable"] });
  saisir(q(div, "taches-titre"), "Préparer la paie");
  const champ = q(q(div, "taches-nouvelle"), "liste-ajout-champ");
  saisir(champ, "Bulletins");
  entree(champ);
  expect(mockPost).not.toHaveBeenCalled();                     // un élément ajouté ne crée pas encore la tâche
  saisir(q(q(div, "taches-nouvelle"), "liste-ajout-champ"), "CNSS");
  entree(q(q(div, "taches-nouvelle"), "liste-ajout-champ"));
  entree(q(q(div, "taches-nouvelle"), "liste-ajout-champ"));   // ligne vide : enregistre
  await attendre();
  expect(mockPost).toHaveBeenCalledTimes(1);
  const corps = mockPost.mock.calls[0][1];
  expect(corps.titre).toBe("Préparer la paie");
  expect(corps.elements.map((e) => e.texte)).toEqual(["Bulletins", "CNSS"]);
});

test("cocher un élément enregistre aussitôt toute la liste", async () => {
  mockPatch.mockResolvedValue({ data: {} });
  const div = await ouvrir({ roles: ["comptable"] });
  act(() => q(div, "element-cocher-e2").click());
  await attendre();
  const [url, corps] = mockPatch.mock.calls[0];
  expect(url).toBe("/me/taches/t2");
  expect(corps.elements.find((e) => e.id === "e2").fait).toBe(true);
});

test("la Direction choisit un membre et voit tâches réalisées et non réalisées, en lecture seule", async () => {
  const div = await ouvrir({ roles: ["direction"] });
  act(() => q(div, "taches-onglet-personnel").click());
  await attendre();
  const select = q(div, "taches-select-membre");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(select, "a1");
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await attendre();
  expect(q(div, "taches-non-realisees").textContent).toContain("Déclarer la TVA");
  expect(q(div, "taches-non-realisees").textContent).toContain("Lettrage");
  expect(q(div, "taches-realisees").textContent).toContain("Payer la CNSS");
  expect(q(div, "taches-realisees").textContent).toContain("05/11/2026");
  expect(q(div, "taches-non-realisees").querySelector('[data-testid="liste-ajout-champ"]')).toBeNull();   // pas de saisie en lecture seule
});
