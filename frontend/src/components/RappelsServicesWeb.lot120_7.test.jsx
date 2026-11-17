/** @jest-environment jsdom */
// Lot 120.7 — fenêtre de rappel : reliquats partiels rappelés ; puce noire, texte bleu clair, montants en gras, rouge, alignés à droite.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";
import RappelsServicesWeb from "./RappelsServicesWeb";

jest.mock("@/lib/api", () => ({
  extractError: () => "erreur",
  apiClient: {
    get: () => Promise.resolve({ data: { rappels: [
      { cle: "2026-11-12:retard-2026-11-17", id: "s1", service: "Maintenances", montant: 145000, devise: "FCFA", payable_avant: "2026-11-12", etat: "en_retard", jours_restants: -5, palier: "retard-2026-11-17" },
      { cle: "None:reliquat", id: "s2", service: "Site ALBARKA", montant: 780000, devise: "FCFA", etat: "partiel", jours_restants: null, palier: "reliquat", total_paye: 200000, reste_a_payer: 580000 },
    ] } }),
    post: () => Promise.resolve({ data: { ok: true } }),
  },
}), { virtual: true });
jest.mock("@/components/ui/button", () => ({ Button: (p) => <button {...p} /> }), { virtual: true });
jest.mock("@/pages/admin/MesServicesWeb", () => ({ EtatService: () => <span>état</span> }), { virtual: true });

test("une puce noire par service, texte bleu clair, montants gras rouge à droite ; le reliquat montre le reste à payer", async () => {
  const c = document.createElement("div"); document.body.appendChild(c);
  await act(async () => { createRoot(c).render(<RappelsServicesWeb />); });
  const lignes = document.querySelectorAll('[data-testid^="rappel-s"]');
  expect(lignes.length).toBe(2);
  expect(document.querySelectorAll('[data-testid="puce-noire"]').length).toBe(2);
  expect(document.querySelector('[data-testid="puce-noire"]').className).toContain("text-black");
  const texte = lignes[0].querySelector(".flex-1");
  expect(texte.style.color).toBe("rgb(2, 119, 181)");                                         // bleu clair #0277B5
  const montants = document.querySelectorAll('[data-testid="montant-rappel"]');
  for (const m of montants) { expect(m.className).toMatch(/font-bold/); expect(m.className).toMatch(/text-red-/); expect(m.className).toMatch(/text-right/); }
  expect(montants[0].textContent.replace(/\s/g, "")).toContain("145000");
  expect(montants[1].textContent.replace(/\s/g, "")).toContain("580000");                       // reliquat = reste à payer
  expect(lignes[1].textContent).toContain("Reliquat à payer");
});
