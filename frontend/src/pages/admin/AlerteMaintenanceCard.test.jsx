/** @jest-environment jsdom */
// Lot 50 — le formulaire « Alerte et maintenance » doit se remplir avec le bandeau enregistré.
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";

const mockGet = jest.fn();
jest.mock("@/lib/api", () => ({ apiClient: { get: (...a) => mockGet(...a), put: jest.fn(), post: jest.fn(), delete: jest.fn() }, extractError: (e, f) => f || "erreur" }), { virtual: true });
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn() } }), { virtual: true });
jest.mock("@/components/ui/button", () => ({ Button: ({ children, ...p }) => <button {...p}>{children}</button> }), { virtual: true });
jest.mock("@/components/ui/input", () => ({ Input: (p) => <input {...p} /> }), { virtual: true });
jest.mock("@/components/ui/label", () => ({ Label: ({ children }) => <label>{children}</label> }), { virtual: true });
jest.mock("@/components/ui/textarea", () => ({ Textarea: (p) => <textarea {...p} /> }), { virtual: true });

import AlerteMaintenanceCard from "./AlerteMaintenanceCard";

const attendre = (ms) => act(() => new Promise((r) => setTimeout(r, ms)));

test("le bandeau enregistré remplit le formulaire (message, gravité, lien, dates)", async () => {
  mockGet.mockImplementation((url) => {
    if (url === "/bandeau/admin") return Promise.resolve({ data: { actif: true, severite: "critical", message: "Incident WhatsApp", image: "data:image/png;base64,AAAA",
      lien_url: "https://exemple.bf/etat", lien_libelle: "Suivre", debut: "2026-10-21T08:00:00+00:00", fin: null, statut: "programme" } });
    if (url === "/maintenance/etat") return Promise.resolve({ data: { phase: "aucune", active: false } });
    return Promise.resolve({ data: { journal: [] } });
  });
  const conteneur = document.createElement("div"); document.body.appendChild(conteneur);
  const racine = createRoot(conteneur);
  await act(async () => { racine.render(<AlerteMaintenanceCard />); });
  await attendre(30);
  expect(conteneur.querySelector('[data-testid="bandeau-message"]').value).toBe("Incident WhatsApp");
  expect(conteneur.querySelector('[data-testid="bandeau-gravite"]').value).toBe("critical");
  expect(conteneur.querySelector('[data-testid="bandeau-debut"]').value).toMatch(/^2026-10-21T\d\d:\d\d$/);
  expect(conteneur.querySelector('[data-testid="bandeau-statut"]').textContent).toContain("Programmé");
  expect(conteneur.querySelector('[data-testid="bandeau-apercu"]')).not.toBeNull();
  act(() => racine.unmount());
});

test("une lecture en échec n'empêche pas le formulaire de se remplir et affiche l'erreur", async () => {
  mockGet.mockImplementation((url) => {
    if (url === "/bandeau/admin") return Promise.resolve({ data: { actif: true, severite: "info", message: "Info", statut: "affiche" } });
    return Promise.reject({ response: { status: 500 } });
  });
  const conteneur = document.createElement("div"); document.body.appendChild(conteneur);
  const racine = createRoot(conteneur);
  await act(async () => { racine.render(<AlerteMaintenanceCard />); });
  await attendre(30);
  expect(conteneur.querySelector('[data-testid="bandeau-message"]').value).toBe("Info");
  expect(conteneur.querySelector('[data-testid="alerte-erreurs"]').textContent).toContain("Lecture incomplète");
  act(() => racine.unmount());
});
