/** @jest-environment jsdom */
// Lot 117 — fenêtre « Du nouveau chez SAWALI » (DG) : paiements et réponses affichés ; se ferme UNIQUEMENT par « J'ai compris » / « Voir les demandes », qui acquittent.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";
import InfosConnexionDG, { libelleSuivi } from "./InfosConnexionDG";

const mockPost = jest.fn(() => Promise.resolve({ data: { ok: true } }));
const mockNavigate = jest.fn();
jest.mock("react-router-dom", () => ({ useNavigate: () => mockNavigate }), { virtual: true });
jest.mock("@/lib/api", () => ({
  apiClient: {
    get: () => Promise.resolve({ data: {
      paiements: [{ id: "t1", recu_le: "2026-11-17T09:30:00+00:00", montant: 75000, operateur: "Orange", tiers: "Awa" }],
      demandes: [{ id: "d1", numero_sawali: "DEM-9", texte: "Corriger la facture", statut: "realisee", realisee_le: "2026-11-16", commentaire: "Livré" }],
      paiements_etat: "ok", jusqu_a: "2026-11-17T10:00:00+00:00" } }),
    post: (...a) => mockPost(...a),
  },
}), { virtual: true });
jest.mock("@/components/ui/button", () => ({ Button: (p) => <button {...p} /> }), { virtual: true });

test("libellé de suivi d'une demande", () => {
  expect(libelleSuivi({ statut: "realisee", realisee_le: "2026-11-16" })).toBe("Réalisée le 16/11/2026");
  expect(libelleSuivi({ statut: "remontee", prevue_le: "2026-11-30" })).toBe("Prévue le 30/11/2026");
  expect(libelleSuivi({ statut: "remontee" })).toBe("Date de réalisation à venir");
  expect(libelleSuivi({ statut: "refusee" })).toBe("Refusée");
});

test("affiche paiements et réponses ; ni clic extérieur ni Échap ne ferment ; « J'ai compris » acquitte jusqu'à la date affichée", async () => {
  const conteneur = document.createElement("div");
  document.body.appendChild(conteneur);
  const racine = createRoot(conteneur);
  await act(async () => { racine.render(<InfosConnexionDG />); });
  const fenetre = () => document.querySelector('[data-testid="infos-connexion-dg"]');
  expect(fenetre()).not.toBeNull();
  expect(fenetre().textContent).toContain("75");                       // montant
  expect(fenetre().textContent).toContain("DEM-9");
  expect(fenetre().textContent).toContain("Réalisée le 16/11/2026");
  await act(async () => { fenetre().click(); document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
  expect(fenetre()).not.toBeNull();                                     // toujours ouverte
  await act(async () => { document.querySelector('[data-testid="btn-infos-compris"]').click(); });
  expect(mockPost).toHaveBeenCalledWith("/me/infos-connexion/ack", { jusqu_a: "2026-11-17T10:00:00+00:00" });
  expect(fenetre()).toBeNull();
  await act(async () => { racine.unmount(); });
});
