/*
  Lot 89 — Aides pour la connexion par empreinte digitale (WebAuthn / passkeys).
  Le navigateur échange des « tampons binaires » (ArrayBuffer) ; le serveur parle en texte (base64url).
  Ce fichier fait la conversion dans les deux sens. L'empreinte elle-même ne quitte JAMAIS l'appareil.
*/

// Texte base64url -> tampon binaire
export function versTampon(texte) {
  const b64 = String(texte).replace(/-/g, "+").replace(/_/g, "/");
  const rempli = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const bin = atob(rempli);
  const octets = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) octets[i] = bin.charCodeAt(i);
  return octets.buffer;
}

// Tampon binaire -> texte base64url
export function versTexte(tampon) {
  const octets = new Uint8Array(tampon);
  let bin = "";
  octets.forEach((o) => { bin += String.fromCharCode(o); });
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Le navigateur sait-il faire de l'empreinte ? (page en HTTPS + WebAuthn disponible)
export function empreinteSupportee() {
  return typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials;
}

// Options du serveur (JSON) -> options du navigateur (tampons binaires) pour une CONNEXION
export function optionsConnexion(o) {
  return {
    ...o,
    challenge: versTampon(o.challenge),
    allowCredentials: (o.allowCredentials || []).map((c) => ({ ...c, id: versTampon(c.id) })),
  };
}

// Options du serveur (JSON) -> options du navigateur pour un ENRÔLEMENT
export function optionsEnrolement(o) {
  return {
    ...o,
    challenge: versTampon(o.challenge),
    user: { ...o.user, id: versTampon(o.user.id) },
    excludeCredentials: (o.excludeCredentials || []).map((c) => ({ ...c, id: versTampon(c.id) })),
  };
}

// Réponse de connexion du navigateur -> JSON pour le serveur
export function reponseConnexion(c) {
  const r = c.response;
  return {
    id: c.id, rawId: versTexte(c.rawId), type: c.type, clientExtensionResults: c.getClientExtensionResults?.() || {},
    response: {
      clientDataJSON: versTexte(r.clientDataJSON), authenticatorData: versTexte(r.authenticatorData),
      signature: versTexte(r.signature), userHandle: r.userHandle ? versTexte(r.userHandle) : undefined,
    },
  };
}

// Réponse d'enrôlement du navigateur -> JSON pour le serveur
export function reponseEnrolement(c) {
  const r = c.response;
  return {
    id: c.id, rawId: versTexte(c.rawId), type: c.type, clientExtensionResults: c.getClientExtensionResults?.() || {},
    response: {
      clientDataJSON: versTexte(r.clientDataJSON), attestationObject: versTexte(r.attestationObject),
      transports: r.getTransports ? r.getTransports() : [],
    },
  };
}
