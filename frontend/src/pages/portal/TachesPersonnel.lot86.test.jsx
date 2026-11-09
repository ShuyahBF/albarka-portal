/** @jest-environment jsdom */
// Lot 86 — bloc « Mes tâches » de Mon compte : replié à l'origine, création, vue Direction.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockPut = jest.fn();
jest.mock("@/lib/api", () => ({ apiClient: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a), put: (...a) => mockPut(...a), patch: jest.fn(), delete: jest.fn() }, extractError: () => "erreur" }), { virtual: true });
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }), { virtual: true });
// L'alias « @/ » n'existe pas sous Jest : doublures simples des composants d'interface
jest.mock("@/components/ui/button", () => ({ Button: (p) => <button {...p} /> }), { virtual: true });
jest.mock("@/components/ui/input", () => ({ Input: (p) => <input {...p} /> }), { virtual: true });
jest.mock("@/components/ui/label", () => ({ Label: (p) => <label {...p} /> }), { virtual: true });
jest.mock("@/components/ui/textarea", () => ({ Textarea: (p) => <textarea {...p} /> }), { virtual: true });
jest.mock("@/components/ui/switch", () => ({ Switch: ({ checked, onCheckedChange, ...r }) => <input type="checkbox" checked={checked} onChange={(e) => onCheckedChange(e.target.checked)} {...r} /> }), { virtual: true });

import TachesPersonnel from "./TachesPersonnel";

const attendre = () => act(() => new Promise((r) => setTimeout(r, 20)));
const TACHES = [{ id: "t1", titre: "Déclarer la TVA", details: "", echeance: "2026-11-15", statut: "a_faire", realisee_le: null }];

function monter(user) {
  const div = document.createElement("div");
  document.body.appendChild(div);
  const racine = createRoot(div);
  act(() => racine.render(<TachesPersonnel user={user} />));
  return div;
}

beforeEach(() => {
  mockGet.mockReset();
  mockGet.mockImplementation((url) => {
    if (url === "/me/taches") return Promise.resolve({ data: TACHES });
    if (url === "/me/taches/rappel") return Promise.resolve({ data: { actif: false, heure: "08:00" } });
    if (url === "/me/taches/personnel") return Promise.resolve({ data: [{ id: "a1", full_name: "Awa", a_faire: 1, faites: 2 }] });
    if (url === "/me/taches/personnel/a1") return Promise.resolve({ data: { membre: { id: "a1" }, taches: [
      ...TACHES, { id: "t2", titre: "Payer la CNSS", statut: "fait", realisee_le: "2026-11-05T09:00:00+00:00" }] } });
    return Promise.reject(new Error(url));
  });
});

test("le bloc est replié à l'origine et ne charge rien avant l'ouverture", async () => {
  const div = monter({ roles: ["comptable"] });
  expect(div.querySelector('[data-testid="taches-contenu"]')).toBeNull();
  expect(mockGet).not.toHaveBeenCalled();
  act(() => div.querySelector('[data-testid="taches-entete"]').click());
  await attendre();
  expect(div.querySelector('[data-testid="taches-contenu"]')).not.toBeNull();
  expect(div.textContent).toContain("Déclarer la TVA");
  expect(div.textContent).toContain("15/11/2026");
  // Un comptable n'a pas l'onglet « Tâches du personnel »
  expect(div.querySelector('[data-testid="taches-onglet-personnel"]')).toBeNull();
});

test("la Direction choisit un membre et voit tâches réalisées et non réalisées", async () => {
  const div = monter({ roles: ["direction"] });
  act(() => div.querySelector('[data-testid="taches-entete"]').click());
  await attendre();
  act(() => div.querySelector('[data-testid="taches-onglet-personnel"]').click());
  await attendre();
  const select = div.querySelector('[data-testid="taches-select-membre"]');
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set;
    setter.call(select, "a1");
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await attendre();
  expect(div.querySelector('[data-testid="taches-non-realisees"]').textContent).toContain("Déclarer la TVA");
  expect(div.querySelector('[data-testid="taches-realisees"]').textContent).toContain("Payer la CNSS");
  expect(div.querySelector('[data-testid="taches-realisees"]').textContent).toContain("05/11/2026");
});
