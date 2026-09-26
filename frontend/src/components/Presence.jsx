/*
  Présence en temps réel (keep-alive) — voir albarka_presence.py.
    - usePresenceHeartbeat() : à monter une fois par page connectée
      (PortalLayout) ; envoie « je suis là » toutes les 25 s, tout de suite
      quand l'onglet change de visibilité, et « hors ligne » à la fermeture.
    - usePresence()          : côté cabinet, état de tous les comptes,
      rafraîchi toutes les 15 s (pas de WebSocket dans l'application).
    - PresenceDot / PresenceLabel : pastille verte (en ligne), orange (onglet
      en arrière-plan), grise (hors ligne) + « vu il y a … ».
*/
import React, { useEffect, useState } from "react";
import { API, apiClient } from "@/lib/api";

const HEARTBEAT_MS = 25000;
const POLL_MS = 15000;

// Signal « hors ligne » qui part même pendant la fermeture de l'onglet
// (fetch keepalive : le jeton d'accès est joint, contrairement à sendBeacon).
export function sendOffline() {
  let token = null;
  try { token = localStorage.getItem("albarka_token"); } catch { /* stockage indisponible */ }
  if (!token) return Promise.resolve();
  return fetch(`${API}/presence/offline`, {
    method: "POST", keepalive: true, headers: { Authorization: `Bearer ${token}` },
  }).catch(() => {});
}

export function usePresenceHeartbeat(enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined;
    // Dernière activité réelle (clavier, souris, défilement, toucher) : sert au
    // tableau de bord « durée jusqu'à la fin de toute activité détectée »
    let lastActivity = Date.now();
    const onActivity = () => { lastActivity = Date.now(); };
    const ACTIVITY = ["mousemove", "mousedown", "keydown", "scroll", "touchstart", "click"];
    ACTIVITY.forEach((ev) => window.addEventListener(ev, onActivity, { passive: true }));
    const beat = () => apiClient.post("/presence/heartbeat", {
      visible: document.visibilityState === "visible",
      page: window.location.pathname,
      last_activity: lastActivity,
    }).catch(() => {});
    beat();
    const t = setInterval(() => { if (!closing) beat(); }, HEARTBEAT_MS);
    // Fermeture de l'onglet : le navigateur émet « onglet masqué » juste avant
    // « pagehide ». Le battement « masqué » est donc différé d'un instant et
    // abandonné si l'onglet se ferme, pour ne pas écraser le « hors ligne ».
    let closing = false;
    const onVisibility = () => {
      if (document.visibilityState === "visible") beat();
      else setTimeout(() => { if (!closing) beat(); }, 800);
    };
    const onHide = () => { closing = true; sendOffline(); };  // fermeture ou navigation hors du portail
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onHide);
    return () => {
      clearInterval(t);
      ACTIVITY.forEach((ev) => window.removeEventListener(ev, onActivity));
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onHide);
    };
  }, [enabled]);
}

export function usePresence(enabled = true) {
  const [state, setState] = useState({ items: {}, counts: { staff_online: 0, client_online: 0 } });
  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    const load = () => apiClient.get("/presence").then(({ data }) => { if (alive) setState(data); }).catch(() => {});
    load();
    const t = setInterval(load, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, [enabled]);
  return state;
}

// « à l'instant », « il y a 5 min », « il y a 3 h », sinon la date
export function sinceText(iso) {
  if (!iso) return "jamais connecté";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "à l'instant";
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`;
  return `le ${new Date(iso).toLocaleDateString("fr-FR")}`;
}

const DOT = { online: "bg-emerald-500", away: "bg-amber-400", offline: "bg-slate-300" };
const LABEL = { online: "En ligne", away: "Absent (onglet en arrière-plan)", offline: "Hors ligne" };

export function PresenceDot({ presence, className = "" }) {
  const st = presence?.status || "offline";
  const title = st === "offline" ? (presence?.last_seen ? `Hors ligne — vu ${sinceText(presence.last_seen)}` : "Jamais connecté") : LABEL[st];
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ring-2 ring-white shrink-0 ${DOT[st]} ${className}`} title={title} aria-label={title} data-status={st} />;
}

export function PresenceLabel({ presence }) {
  const st = presence?.status || "offline";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs" data-testid="presence-label" data-status={st}>
      <PresenceDot presence={presence} />
      {st === "offline" ? <span className="text-muted-foreground">{presence?.last_seen ? `Vu ${sinceText(presence.last_seen)}` : "Jamais connecté"}</span>
        : <span className={st === "online" ? "text-emerald-700" : "text-amber-700"}>{st === "online" ? "En ligne" : "Absent"}</span>}
    </span>
  );
}
