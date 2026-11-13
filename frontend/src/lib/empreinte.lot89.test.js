/* Lot 89 — conversions base64url <-> tampon binaire de la connexion par empreinte. */
import { versTampon, versTexte, optionsConnexion } from "./empreinte";

test("aller-retour base64url", () => {
  const texte = "AQID_-4"; // octets 1,2,3,255,238
  expect(versTexte(versTampon(texte))).toBe(texte);
  expect(Array.from(new Uint8Array(versTampon(texte)))).toEqual([1, 2, 3, 255, 238]);
});

test("options de connexion : le défi devient un tampon binaire", () => {
  const o = optionsConnexion({ challenge: "AQID", rpId: "x.bf", allowCredentials: [] });
  expect(o.challenge.byteLength).toBe(3);
  expect(o.rpId).toBe("x.bf");
});
