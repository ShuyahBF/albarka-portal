// sonNotification.js — Lot 62 : son d'alerte « nouveau message WhatsApp », partagé par toutes les pages du portail.
//
// - jouerBip()          : petit bip de 0,3 s généré par le navigateur (WebAudio : aucun fichier son à charger) ;
// - sonActif()          : le son est-il activé ? Réglage mémorisé dans ce navigateur ;
// - definirSonActif(v)  : active / coupe le son.
// La clé de mémorisation est celle déjà utilisée par le bouton « Alertes activées / désactivées » de la page WhatsApp :
// un seul réglage pour la page WhatsApp ET pour toutes les autres pages du portail.
export const CLE_ALERTES_WA = "albarka:wa:notif";

export const sonActif = () => {
  try { return localStorage.getItem(CLE_ALERTES_WA) !== "0"; } catch { return true; }
};

export const definirSonActif = (actif) => {
  try { localStorage.setItem(CLE_ALERTES_WA, actif ? "1" : "0"); } catch { /* navigateur sans mémoire : sans importance */ }
};

// Bip de 660 Hz (le navigateur n'autorise le son qu'après un premier clic sur la page : sinon, silence sans erreur)
export function jouerBip() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.type = "sine"; osc.frequency.value = 660;
    gain.gain.setValueAtTime(0.001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
    osc.start(); osc.stop(ctx.currentTime + 0.3);
    setTimeout(() => ctx.close && ctx.close(), 500);
  } catch { /* son impossible : sans importance */ }
}
