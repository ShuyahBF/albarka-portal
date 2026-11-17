// Lot 120.10 — « Des modifications ont été apportées dans cette fenêtre. Les envoyer à SAWALI ? »
// Le site utilise un routeur classique (BrowserRouter) : il ne sait pas bloquer un changement de page. On intercepte donc le CLIC sur un lien du site pendant qu'il existe
// des modifications non envoyées ; l'écran pose la question, puis navigue lui-même. Logique pure (testée) : sortieAvecQuestion.test.js.

/** Rend le chemin de destination (« /admin/xxx?y#z ») si le clic quitte la page courante vers une autre page DU SITE ; sinon null (clic à laisser passer). */
export function destinationInterceptee(evenement, lien, location) {
  if (!lien || evenement.defaultPrevented) return null;
  if (evenement.button !== 0 || evenement.metaKey || evenement.ctrlKey || evenement.shiftKey || evenement.altKey) return null;   // nouvel onglet, etc. : on ne s'en mêle pas
  if ((lien.target && lien.target !== "_self") || (lien.hasAttribute && lien.hasAttribute("download"))) return null;
  let u;
  try { u = new URL(lien.getAttribute("href") || "", location.href); } catch { return null; }
  if (u.origin !== location.origin) return null;                                            // lien externe : hors sujet
  if (u.pathname === location.pathname && u.search === location.search) return null;        // même page (ancre, bouton) : on reste
  return u.pathname + u.search + u.hash;
}

/** Pendant que `actif` est vrai : intercepte les clics qui quittent la page (surSortie reçoit la destination) et fait confirmer la fermeture de l'onglet par le navigateur. */
export function surveillerSortie(actif, surSortie, doc = document, fen = window) {
  if (!actif) return () => {};
  const clic = (e) => {
    const lien = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    const dest = destinationInterceptee(e, lien, fen.location);
    if (dest) { e.preventDefault(); e.stopPropagation(); surSortie(dest); }
  };
  const avantFermeture = (e) => { e.preventDefault(); e.returnValue = ""; };                // message générique du navigateur (le texte n'est plus personnalisable)
  doc.addEventListener("click", clic, true);
  fen.addEventListener("beforeunload", avantFermeture);
  return () => { doc.removeEventListener("click", clic, true); fen.removeEventListener("beforeunload", avantFermeture); };
}
