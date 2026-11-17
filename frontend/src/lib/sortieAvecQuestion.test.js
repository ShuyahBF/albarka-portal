import { destinationInterceptee } from "./sortieAvecQuestion";

const loc = { href: "https://albarka.test/admin/demandes-sawali", origin: "https://albarka.test", pathname: "/admin/demandes-sawali", search: "" };
const lien = (href, extra = {}) => ({ getAttribute: () => href, hasAttribute: () => false, target: "", ...extra });
const clic = (extra = {}) => ({ defaultPrevented: false, button: 0, ...extra });

test("un lien vers une autre page du site est intercepté", () => {
  expect(destinationInterceptee(clic(), lien("/admin/clients?x=1#a"), loc)).toBe("/admin/clients?x=1#a");
  expect(destinationInterceptee(clic(), lien("https://albarka.test/admin/paie"), loc)).toBe("/admin/paie");
});
test("même page, lien externe, nouvel onglet, téléchargement, Ctrl+clic : on laisse passer", () => {
  expect(destinationInterceptee(clic(), lien("/admin/demandes-sawali"), loc)).toBeNull();
  expect(destinationInterceptee(clic(), lien("#haut"), loc)).toBeNull();
  expect(destinationInterceptee(clic(), lien("https://autre.site/x"), loc)).toBeNull();
  expect(destinationInterceptee(clic(), lien("/admin/clients", { target: "_blank" }), loc)).toBeNull();
  expect(destinationInterceptee(clic(), lien("/f.pdf", { hasAttribute: () => true }), loc)).toBeNull();
  expect(destinationInterceptee(clic({ ctrlKey: true }), lien("/admin/clients"), loc)).toBeNull();
  expect(destinationInterceptee(clic({ button: 1 }), lien("/admin/clients"), loc)).toBeNull();
  expect(destinationInterceptee(clic(), null, loc)).toBeNull();
});
