/*
  Lot 33 — Conversations WhatsApp : la vue par défaut est la liste des contacts propres au cabinet ;
  un contact se crée sur place (sans quitter la messagerie) puis son fil s'ouvre.
  Le serveur est simulé.
*/
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react-dom/test-utils";

const mockPost = jest.fn();
const mockGet = jest.fn();
jest.mock("@/lib/api", () => ({
  apiClient: { get: (...a) => mockGet(...a), post: (...a) => mockPost(...a), patch: jest.fn(), delete: jest.fn() },
  extractError: (e, d) => d || "erreur",
}), { virtual: true });
// Routeur et composants d'interface (alias « @/ » absent du test) : remplacés par des versions minimales
jest.mock("react-router-dom", () => ({ useNavigate: () => jest.fn() }), { virtual: true });
const passe = (Tag = "div") => ({ children, ...p }) => React.createElement(Tag, {}, children);
jest.mock("@/components/ui/button", () => ({ Button: ({ children, onClick, type, disabled, ...p }) => <button type={type} onClick={onClick} disabled={disabled} data-testid={p["data-testid"]}>{children}</button> }), { virtual: true });
jest.mock("@/components/ui/input", () => ({ Input: (p) => <input {...p} /> }), { virtual: true });
jest.mock("@/components/ui/textarea", () => ({ Textarea: (p) => <textarea {...p} /> }), { virtual: true });
jest.mock("@/components/ui/badge", () => ({ Badge: ({ children }) => <span>{children}</span> }), { virtual: true });
jest.mock("@/components/ui/dropdown-menu", () => { const P = ({ children }) => <div>{children}</div>; return { DropdownMenu: P, DropdownMenuTrigger: P, DropdownMenuContent: P, DropdownMenuItem: P, DropdownMenuLabel: P, DropdownMenuSeparator: P }; }, { virtual: true });
jest.mock("@/components/ui/dialog", () => { const P = ({ children }) => <div>{children}</div>; return { Dialog: ({ open, children }) => (open ? <div>{children}</div> : null), DialogContent: P, DialogHeader: P, DialogTitle: P, DialogFooter: P, DialogDescription: P }; }, { virtual: true });
jest.mock("@/components/ui/command", () => { const P = ({ children }) => <div>{children}</div>; return { Command: P, CommandEmpty: P, CommandGroup: P, CommandInput: P, CommandItem: P, CommandList: P }; }, { virtual: true });
jest.mock("sonner", () => ({ toast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() } }), { virtual: true });
jest.mock("@/contexts/AuthContext", () => ({ useAuth: () => ({ user: { email: "admin@sawalismartsystems.com" } }) }), { virtual: true });
jest.mock("@/components/Presence", () => ({ PresenceDot: () => null, PresenceLabel: () => null }), { virtual: true });

import AdminWhatsAppConversations from "./AdminWhatsAppConversations";

const attendre = (ms) => act(() => new Promise((r) => setTimeout(r, ms)));
const saisir = async (el, v) => {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  await act(async () => { setter.call(el, v); el.dispatchEvent(new Event("input", { bubbles: true })); });
};

beforeEach(() => {
  window.HTMLElement.prototype.scrollTo = jest.fn();   // absent de jsdom
  mockGet.mockReset(); mockPost.mockReset();
  mockGet.mockImplementation((url) => {
    if (url === "/contacts") return Promise.resolve({ data: [
      { id: "c1", scope: "cabinet", full_name: "Awa Cabinet", phone: "+22670000001", channels: ["whatsapp"] },
      { id: "c2", scope: "client", full_name: "Client Autre", phone: "+22670000002", channels: ["whatsapp"] }] });
    if (url === "/whatsapp/conversations") return Promise.resolve({ data: [] });
    return Promise.resolve({ data: [] });
  });
  mockPost.mockResolvedValue({ data: { id: "c3", full_name: "Nouveau Cab", phone: "+22670112233" } });
});

test("vue par défaut = contacts du cabinet seulement, création sur place avec numéro normalisé", async () => {
  const conteneur = document.createElement("div"); document.body.appendChild(conteneur);
  const racine = createRoot(conteneur);
  await act(async () => { racine.render(<AdminWhatsAppConversations />); });
  await attendre(30);
  expect(conteneur.textContent).toContain("Awa Cabinet");
  expect(conteneur.textContent).not.toContain("Client Autre");          // les contacts clients n'y figurent pas
  await act(async () => { conteneur.querySelector('[data-testid="wa-inbox-new-contact-btn"]').click(); });
  await saisir(conteneur.querySelector('[data-testid="wa-inbox-nc-name"]'), "Nouveau Cab");
  await saisir(conteneur.querySelector('[data-testid="wa-inbox-nc-phone"]'), "70 11 22 33");
  await act(async () => { conteneur.querySelector('[data-testid="wa-inbox-new-contact-form"]').dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  await attendre(30);
  const [url, corps] = mockPost.mock.calls[0];
  expect(url).toBe("/contacts");
  expect(corps).toMatchObject({ scope: "cabinet", full_name: "Nouveau Cab", phone: "+22670112233", channels: ["whatsapp"] });
  act(() => racine.unmount());
});

test("lot 34 : le super-admin voit « Vider les conversations » et doit taper SUPPRIMER pour confirmer", async () => {
  const conteneur = document.createElement("div"); document.body.appendChild(conteneur);
  const racine = createRoot(conteneur);
  await act(async () => { racine.render(<AdminWhatsAppConversations />); });
  await attendre(30);
  mockPost.mockClear();
  await act(async () => { conteneur.querySelector('[data-testid="wa-inbox-purge-btn"]').click(); });
  const bouton = conteneur.querySelector('[data-testid="wa-inbox-purge-confirm"]');
  expect(bouton.disabled).toBe(true);                                   // pas de confirmation sans le mot SUPPRIMER
  await saisir(conteneur.querySelector('[data-testid="wa-inbox-purge-input"]'), "SUPPRIMER");
  expect(conteneur.querySelector('[data-testid="wa-inbox-purge-confirm"]').disabled).toBe(false);
  mockPost.mockResolvedValueOnce({ data: { ok: true, messages_supprimes: 3, etiquettes_supprimees: 1 } });
  await act(async () => { conteneur.querySelector('[data-testid="wa-inbox-purge-confirm"]').click(); });
  await attendre(30);
  expect(mockPost).toHaveBeenCalledWith("/whatsapp/conversations/purge", { confirmation: "SUPPRIMER" });
  act(() => racine.unmount());
});
