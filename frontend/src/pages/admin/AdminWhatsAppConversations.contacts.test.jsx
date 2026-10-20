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
jest.mock("@/components/wa/SelecteurEmojis", () => ({ __esModule: true, default: ({ onChoisir }) => <button type="button" data-testid="wa-inbox-emoji-btn" onClick={() => onChoisir("😀")}>emoji</button> }), { virtual: true });
jest.mock("@/components/wa/PieceJointeMessage", () => ({ __esModule: true, default: ({ message }) => <span data-testid={`wa-msg-fichier-${message.id}`}>{message.media_filename}</span> }), { virtual: true });
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
    if (url.startsWith("/whatsapp/conversations/") && url.endsWith("/messages")) return Promise.resolve({ data: [
      { id: "a1", direction: "inbound", phone: "+22670000001", message_type: "text", body: "Bonjour cabinet", contact_name: "Awa Cabinet", created_at: "2026-10-19T22:34:00Z" },
      { id: "a2", direction: "outbound", phone: "+22670000001", message_type: "text", body: "Je vous écoute", sent_by_name: "Cabinet", created_at: "2026-10-19T22:35:00Z",
        wa_status: "read", wa_status_times: { sent: "2026-10-19T22:35:01Z", delivered: "2026-10-19T22:35:05Z", read: "2026-10-19T22:36:00Z" } }] });
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


test("lot 38 : répondre en citant un message envoie reply_to_id ; l'état Lu est affiché sous le message", async () => {
  const conteneur = document.createElement("div"); document.body.appendChild(conteneur);
  const racine = createRoot(conteneur);
  await act(async () => { racine.render(<AdminWhatsAppConversations />); });
  await attendre(30);
  await act(async () => { conteneur.querySelector('[data-testid="wa-inbox-contact-c1"]').click(); });
  await attendre(80);
  expect(conteneur.querySelector('[data-testid="wa-msg-etat-a2"]').textContent).toContain("Lu 22:36");
  await act(async () => { conteneur.querySelector('[data-testid="wa-msg-repondre-a1"]').click(); });
  expect(conteneur.querySelector('[data-testid="wa-inbox-citation-barre"]').textContent).toContain("Bonjour cabinet");
  const champ = conteneur.querySelector('[data-testid="wa-inbox-reply-input"]');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
  await act(async () => { setter.call(champ, "Merci"); champ.dispatchEvent(new Event("input", { bubbles: true })); });
  mockPost.mockClear();
  mockPost.mockResolvedValueOnce({ data: { ok: true, result: {} } });
  await act(async () => { conteneur.querySelector('[data-testid="wa-inbox-send-btn"]').click(); });
  await attendre(30);
  expect(mockPost).toHaveBeenCalledWith("/whatsapp/conversations/%2B22670000001/reply", { body: "Merci", reply_to_id: "a1" });
  expect(conteneur.querySelector('[data-testid="wa-inbox-citation-barre"]')).toBeNull();      // citation retirée après l'envoi
  act(() => racine.unmount());
});


test("lot 45 : emoji inséré, document joint envoyé en multipart avec la légende ; vidéo refusée", async () => {
  const conteneur = document.createElement("div"); document.body.appendChild(conteneur);
  const racine = createRoot(conteneur);
  await act(async () => { racine.render(<AdminWhatsAppConversations />); });
  await attendre(30);
  await act(async () => { conteneur.querySelector('[data-testid="wa-inbox-contact-c1"]').click(); });
  await attendre(80);
  // Emoji : inséré dans la zone de saisie
  await act(async () => { conteneur.querySelector('[data-testid="wa-inbox-emoji-btn"]').click(); });
  expect(conteneur.querySelector('[data-testid="wa-inbox-reply-input"]').value).toContain("😀");
  // Vidéo : refusée, aucun fichier joint
  const entree = conteneur.querySelector('[data-testid="wa-inbox-fichier-input"]');
  const choisir = async (f) => { Object.defineProperty(entree, "files", { value: [f], configurable: true }); await act(async () => { entree.dispatchEvent(new Event("change", { bubbles: true })); }); };
  await choisir(new File(["x"], "film.mp4", { type: "video/mp4" }));
  expect(conteneur.querySelector('[data-testid="wa-inbox-fichier-joint"]')).toBeNull();
  // PDF : puce affichée puis envoi en multipart
  await choisir(new File(["%PDF"], "bulletin.pdf", { type: "application/pdf" }));
  expect(conteneur.querySelector('[data-testid="wa-inbox-fichier-joint"]').textContent).toContain("bulletin.pdf");
  mockPost.mockClear();
  mockPost.mockResolvedValueOnce({ data: { ok: true, result: {} } });
  await act(async () => { conteneur.querySelector('[data-testid="wa-inbox-send-btn"]').click(); });
  await attendre(30);
  const [url, corps] = mockPost.mock.calls[0];
  expect(url).toBe("/whatsapp/conversations/%2B22670000001/send-file");
  expect(corps.get("fichier").name).toBe("bulletin.pdf");
  expect(corps.get("legende")).toContain("😀");
  expect(conteneur.querySelector('[data-testid="wa-inbox-fichier-joint"]')).toBeNull();        // puce retirée après l'envoi
  act(() => racine.unmount());
});
