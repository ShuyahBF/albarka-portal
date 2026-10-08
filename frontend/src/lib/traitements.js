// traitements.js — Lot 18 : menu dépliable « Traitements » du cabinet (source UNIQUE des sous-menus et des rôles).
//
// Demande du propriétaire (08/10/2026) : sous « Documents & modèles », un menu pliable « Traitements » avec trois
// sous-menus — Fiscal, Comptable, RH — qui ouvrent pour l'instant une page « Bientôt disponible ».
// Réservé au CABINET (jamais aux clients) ; chaque collaborateur ne voit que les sous-menus de son métier.
// Le Superviseur voit tout ; le DG a les droits de la Direction (règle commune de PortalLayout.allowedFor).
export const TRAITEMENTS = [
  { cle: "fiscal", label: "Fiscal", roles: ["superviseur", "direction", "fiscaliste"] },
  { cle: "comptable", label: "Comptable", roles: ["superviseur", "direction", "comptable", "aide_comptable"] },
  { cle: "rh", label: "RH", roles: ["superviseur", "direction", "administrateur", "rh"] },
];

// Vrai si l'utilisateur (ses rôles) a accès au traitement donné (même règle que le menu)
export function accesTraitement(cle, roles = []) {
  const t = TRAITEMENTS.find((x) => x.cle === cle);
  if (!t) return false;
  if (roles.includes("superviseur")) return true;
  const effectifs = roles.includes("dg") ? [...roles, "direction"] : roles;
  return t.roles.some((r) => effectifs.includes(r));
}
