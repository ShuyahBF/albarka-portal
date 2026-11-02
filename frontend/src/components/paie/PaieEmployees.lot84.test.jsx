/** @jest-environment jsdom */
// Lot 84 — fiche paie du salarié : case « Exonéré de la cotisation CNSS » et rubriques SND / SFED / CENAMU.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;   // évite les avertissements « act(...) » de React 19 sous Jest
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/lib/api", () => ({ apiClient: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a), put: jest.fn(), delete: jest.fn() }, extractError: () => "erreur" }), { virtual: true });
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }), { virtual: true });

// L'alias « @/ » n'existe pas sous Jest : doublure fidèle de paieCommon (même sélecteur d'employeur, même format des montants)
jest.mock("@/components/paie/paieCommon", () => {
  const R = require("react");
  return {
    GREEN: "#0F6B4A",
    fcfa: (v) => (v === null || v === undefined || v === "" ? "—" : Math.round(Number(v)).toLocaleString("fr-FR")),
    useEmployers: () => { const [items, setItems] = R.useState([]); R.useEffect(() => { mockGet("/hr/paie/employeurs").then(({ data }) => setItems(data.items || [])); }, []); return items; },
    EmployerSelect: ({ value, onChange, employers }) => (
      <select value={value} onChange={(e) => onChange(e.target.value)} data-testid="paie-employer"><option value="">—</option>
        {employers.map((e) => <option key={e.employer_id} value={e.employer_id}>{e.name}</option>)}</select>),
  };
}, { virtual: true });

import PaieEmployees from "./PaieEmployees";

const attendre = (ms) => act(() => new Promise((r) => setTimeout(r, ms)));
// Réglage du modèle de l'employeur : SND à 1 % du brut, SFED à 2 000 FCFA, CENAMU non réglée
const PARAMS = { allowances: [], flat_abatement: { mode: "single" }, in_kind: { label: "Avantage en nature" },
  special_deductions: [{ key: "snd", label: "SND", mode: "percent", base: "gross", value: 1 }, { key: "sfed", label: "SFED", mode: "amount", base: "gross", value: 2000 },
    { key: "cenamu", label: "CENAMU", mode: "percent", base: "gross", value: 0 }] };

// Saisie dans un champ React contrôlé (le setter natif déclenche bien l'événement « input »)
function saisir(el, valeur) {
  const proto = el.tagName === "SELECT" ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(el, valeur);
  el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
}

test("la fiche propose la case CNSS et les trois rubriques, et les envoie à l'enregistrement et au calcul en direct", async () => {
  mockGet.mockImplementation((url) => {
    if (url === "/hr/paie/employeurs") return Promise.resolve({ data: { items: [{ employer_id: "c1", name: "PHARMACIE SOLEIL", employees_count: 0 }] } });
    if (url === "/hr/paie/employees") return Promise.resolve({ data: { items: [] } });
    return Promise.resolve({ data: { params: PARAMS, officine: false } });
  });
  mockPost.mockImplementation((url) => Promise.resolve({ data: url.endsWith("/simulate") ? { gross: 300000, cnss: 0, cnss_exempt: true, iuts_base: 200000, iuts: 10000, net: 290000,
    special_deductions: [{ label: "SND", amount: 3000 }], net_to_pay: 280000, years_of_service: 0, seniority_rate: 0 } : {} }));
  const conteneur = document.createElement("div"); document.body.appendChild(conteneur);
  const racine = createRoot(conteneur);
  await act(async () => { racine.render(<PaieEmployees />); });
  await attendre(20);
  await act(async () => { saisir(conteneur.querySelector('[data-testid="paie-employer"]'), "c1"); });
  await attendre(20);
  await act(async () => { conteneur.querySelector('[data-testid="emp-new"]').click(); });
  await attendre(20);

  // Les trois rubriques et la case d'exonération sont présentes ; le réglage du modèle est indiqué en grisé
  const q = (id) => conteneur.querySelector(`[data-testid="${id}"]`);
  expect(q("emp-cnss-exempt")).not.toBeNull();
  expect(q("emp-rub-snd-valeur").placeholder).toBe("1 % du salaire brut");
  expect(q("emp-rub-sfed-valeur").placeholder).toContain("2");
  expect(q("emp-rub-cenamu-valeur").placeholder).toBe("non réglée");

  // Cocher l'exonération, régler la SND à 2 % du salaire de base et la CENAMU à 1 500 FCFA
  await act(async () => { q("emp-cnss-exempt").click(); });
  await act(async () => { saisir(q("emp-name"), "OUEDRAOGO Paul"); saisir(q("emp-rub-snd-valeur"), "2");
    saisir(q("emp-rub-snd").querySelectorAll("select")[1], "base"); saisir(q("emp-rub-cenamu").querySelectorAll("select")[0], "amount"); });
  await act(async () => { saisir(q("emp-rub-cenamu-valeur"), "1500"); });
  await attendre(450);                                             // le calcul en direct attend la fin de la saisie

  const sim = mockPost.mock.calls.filter(([u]) => u === "/hr/paie/simulate").pop()[1].employee;
  expect(sim.cnss_exempt).toBe(true);
  expect(sim.special_deductions).toEqual({ snd: { mode: "percent", base: "base", value: 2 }, cenamu: { mode: "amount", base: "gross", value: 1500 } });
  expect(q("emp-calc").textContent).toContain("CNSS (exonéré)");
  expect(q("emp-calc").textContent).toContain("Base IUTS");
  expect(q("emp-calc").textContent).toContain("SND");

  await act(async () => { q("emp-save").click(); });
  const corps = mockPost.mock.calls.find(([u]) => u === "/hr/paie/employees")[1];
  expect(corps.cnss_exempt).toBe(true);
  expect(corps.special_deductions.sfed).toBeUndefined();            // rubrique laissée vide : le modèle de l'employeur s'applique
  expect(corps.special_deductions.snd.value).toBe(2);
  act(() => racine.unmount());
});
