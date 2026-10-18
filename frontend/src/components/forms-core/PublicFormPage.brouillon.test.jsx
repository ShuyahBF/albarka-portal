/*
  Lot 28.4 — brouillon automatique du formulaire public : sauvegarde sur l'appareil, restauration à la réouverture,
  effacement après l'envoi. Le serveur et le moteur de questions sont simulés.
*/
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";

const mockPost = jest.fn();
const mockGet = jest.fn();
jest.mock("@/lib/api", () => ({
  apiClient: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a) },
}), { virtual: true });   // l'alias « @/ » n'existe que pour le build du site
// Moteur de questions simplifié : une zone de saisie et le bouton d'envoi
jest.mock("./FormRenderer", () => (props) => (
  <div>
    <input data-testid="champ" value={props.value.q1 || ""} onChange={(e) => props.onChange({ ...props.value, q1: e.target.value })} />
    <button data-testid="envoyer" onClick={props.onSubmit}>Envoyer</button>
  </div>
));

import PublicFormPage from "./PublicFormPage";

const attendre = (ms) => act(() => new Promise((r) => setTimeout(r, ms)));
const saisir = async (el, valeur) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  await act(async () => { setter.call(el, valeur); el.dispatchEvent(new Event("input", { bubbles: true })); });
};
let conteneur;
const monter = async () => {
  conteneur = document.createElement("div"); document.body.appendChild(conteneur);
  const racine = createRoot(conteneur);
  await act(async () => { racine.render(<PublicFormPage token="jeton123" />); });
  await attendre(20);
  return racine;
};

// La configuration de test du site réinitialise les simulations avant chaque test : on les redéfinit ici
beforeEach(() => {
  window.localStorage.clear();
  mockGet.mockImplementation(() => Promise.resolve({ data: { form: { title: "Paie", settings: {} }, source: "public" } }));
  mockPost.mockImplementation(() => Promise.resolve({ data: { message: "Merci" } }));
});
afterEach(() => { conteneur?.remove(); });

test("la saisie est gardée puis restaurée à la réouverture", async () => {
  let racine = await monter();
  await saisir(conteneur.querySelector('[data-testid="champ"]'), "21 salariés");
  await attendre(800);                                         // délai d'enregistrement automatique
  expect(window.localStorage.getItem("forms-brouillon:/public/forms:jeton123")).toContain("21 salariés");
  act(() => racine.unmount()); conteneur.remove();
  racine = await monter();                                     // « coupure de courant » : la page est rouverte
  expect(conteneur.querySelector('[data-testid="champ"]').value).toBe("21 salariés");
  expect(conteneur.textContent).toContain("a été restauré");
});

test("le brouillon est effacé après l'envoi", async () => {
  await monter();
  await saisir(conteneur.querySelector('[data-testid="champ"]'), "oui");
  await attendre(800);
  await act(async () => { conteneur.querySelector('[data-testid="envoyer"]').click(); });
  await attendre(50);
  expect(mockPost).toHaveBeenCalled();
  expect(window.localStorage.getItem("forms-brouillon:/public/forms:jeton123")).toBeNull();
});

test("un brouillon de plus de 30 jours est ignoré", async () => {
  window.localStorage.setItem("forms-brouillon:/public/forms:jeton123",
    JSON.stringify({ at: Date.now() - 31 * 24 * 3600 * 1000, data: { q1: "ancien" }, respondent: { name: "", email: "" } }));
  await monter();
  expect(conteneur.querySelector('[data-testid="champ"]').value).toBe("");
});

// --- Lot 32 : plus d'écran blanc si l'affichage plante
test("un plantage d'affichage montre un message, garde les réponses et signale l'incident", async () => {
  jest.resetModules();
  const erreurConsole = jest.spyOn(console, "error").mockImplementation(() => {});   // React journalise le plantage attendu
  mockGet.mockImplementation(() => Promise.resolve({ data: { form: { title: "Paie", settings: {} }, source: "public" } }));
  mockPost.mockImplementation(() => Promise.resolve({ data: {} }));
  const Plante = () => { throw new Error("objet affiché par erreur"); };
  const { BoiteErreur } = require("./PublicFormPage");
  conteneur = document.createElement("div"); document.body.appendChild(conteneur);
  const signaler = jest.fn();
  await act(async () => { createRoot(conteneur).render(<BoiteErreur signaler={signaler}><Plante /></BoiteErreur>); });
  expect(conteneur.querySelector('[data-testid="public-form-plantage"]')).not.toBeNull();
  expect(conteneur.textContent).toContain("gardées sur cet appareil");
  expect(signaler).toHaveBeenCalledWith(expect.objectContaining({ message: "objet affiché par erreur" }));
  erreurConsole.mockRestore();
});
