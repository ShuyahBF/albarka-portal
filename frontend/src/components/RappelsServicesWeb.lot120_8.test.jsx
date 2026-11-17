/** @jest-environment jsdom */
// Lot 120.8 — le rappel du DG réessaie quand le serveur est indisponible à la connexion (redéploiement) ; « déjà vu » ne survit pas à une déconnexion.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";
import RappelsServicesWeb from "./RappelsServicesWeb";

let mockAppels = 0;
jest.mock("@/lib/api", () => ({
  extractError: () => "erreur",
  apiClient: {
    get: () => { mockAppels += 1; return mockAppels === 1 ? Promise.reject(new Error("502")) : Promise.resolve({ data: { rappels: [
      { cle: "2026-11-12:retard-2026-11-17", id: "s1", service: "Maintenances", montant: 145000, devise: "FCFA", payable_avant: "2026-11-12", etat: "en_retard", jours_restants: -5, palier: "retard-2026-11-17" }] } }); },
    post: () => Promise.resolve({ data: { ok: true } }),
  },
}), { virtual: true });
jest.mock("@/components/ui/button", () => ({ Button: (p) => <button {...p} /> }), { virtual: true });
jest.mock("@/pages/admin/MesServicesWeb", () => ({ EtatService: () => <span>état</span> }), { virtual: true });

test("1er appel en échec (serveur en redéploiement) : nouvel essai, la fenêtre s'ouvre ensuite ; onFini seulement après la réponse définitive", async () => {
  jest.useFakeTimers();
  const fini = jest.fn();
  const c = document.createElement("div"); document.body.appendChild(c);
  await act(async () => { createRoot(c).render(<RappelsServicesWeb onFini={fini} />); });
  expect(document.querySelector('[data-testid="rappels-services-web"]')).toBeNull();
  expect(fini).not.toHaveBeenCalled();                                  // pas d'abandon silencieux
  await act(async () => { jest.advanceTimersByTime(5100); });
  expect(document.querySelector('[data-testid="rappels-services-web"]')).not.toBeNull();
  jest.useRealTimers();
});
