/** @jest-environment jsdom */
// Lot 90 — fenêtre de rappel des services web : se ferme UNIQUEMENT par « J'ai compris » (ni clic extérieur, ni Échap, ni ×).
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";
import RappelsServicesWeb from "./RappelsServicesWeb";

const mockPost = jest.fn(() => Promise.resolve({ data: { ok: true } }));
jest.mock("@/lib/api", () => ({
  extractError: () => "erreur",
  apiClient: {
    get: () => Promise.resolve({ data: { rappels: [
      { cle: "2026-12-01:3", id: "s1", service: "Hébergement", montant: 25000, devise: "FCFA", payable_avant: "2026-12-01", etat: "bientot", jours_restants: 3 },
    ] } }),
    post: (...a) => mockPost(...a),
  },
}), { virtual: true });

jest.mock("@/components/ui/button", () => ({ Button: (p) => <button {...p} /> }), { virtual: true });
jest.mock("@/pages/admin/MesServicesWeb", () => ({ EtatService: () => <span>état</span> }), { virtual: true });

test("ni clic à l'extérieur, ni Échap ne ferment ; « J'ai compris » ferme et acquitte", async () => {
  const conteneur = document.createElement("div");
  document.body.appendChild(conteneur);
  const racine = createRoot(conteneur);
  await act(async () => { racine.render(<RappelsServicesWeb />); });
  const fenetre = () => document.querySelector('[data-testid="rappels-services-web"]');
  expect(fenetre()).not.toBeNull();
  // Aucun bouton hormis « J'ai compris » : pas de bouton de fermeture
  expect(Array.from(fenetre().querySelectorAll("button")).map((b) => b.textContent.trim())).toEqual(["J'ai compris"]);
  // Clic sur le fond et touche Échap : la fenêtre reste ouverte
  await act(async () => { fenetre().dispatchEvent(new MouseEvent("click", { bubbles: true })); });
  await act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
  expect(fenetre()).not.toBeNull();
  // « J'ai compris » : acquittement envoyé, fenêtre fermée
  await act(async () => { fenetre().querySelector('[data-testid="btn-jai-compris"]').dispatchEvent(new MouseEvent("click", { bubbles: true })); });
  expect(mockPost).toHaveBeenCalledWith("/me/services-web/rappels/ack", { cles: ["2026-12-01:3"] });
  expect(fenetre()).toBeNull();
});
