/*
  « Notifications sur cet appareil » (espace client) — active les
  notifications push du navigateur : le client est prévenu des documents que
  le cabinet met à sa disposition, même portail fermé.
  - Android / ordinateur : Chrome, Edge, Firefox ;
  - iPhone / iPad : seulement si le portail a été AJOUTÉ À L'ÉCRAN D'ACCUEIL
    (iOS 16.4+) — un message l'explique sinon.
  API : /push/public-key, /push/subscribe, /push/unsubscribe, /push/test
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Bell, BellOff, BellRing } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";

const b64ToBytes = (b64) => {
  const s = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
};
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent);
const isStandalone = () => window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true;

export default function PushOptIn() {
  const supported = typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const [state, setState] = useState("loading"); // loading | on | off | denied | unsupported | ios-install
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!supported) { setState(isIOS() && !isStandalone() ? "ios-install" : "unsupported"); return; }
    if (Notification.permission === "denied") { setState("denied"); return; }
    navigator.serviceWorker.register("/sw.js")
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => setState(sub ? "on" : "off"))
      .catch(() => setState("off"));
  }, [supported]);

  // Activer : autorisation du navigateur, abonnement, enregistrement côté portail
  const enable = async () => {
    setBusy(true);
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { setState(perm === "denied" ? "denied" : "off"); return; }
      const reg = await navigator.serviceWorker.register("/sw.js");
      await navigator.serviceWorker.ready;
      const { data } = await apiClient.get("/push/public-key");
      // Abonnement auprès du service de push du navigateur (Google, Mozilla, Apple) ;
      // abandon au bout de 20 s s'il ne répond pas, avec un message clair
      const sub = await Promise.race([
        reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(data.public_key) }),
        new Promise((_, reject) => setTimeout(() => reject(new Error("Le service de notifications du navigateur ne répond pas. Réessayez plus tard.")), 20000)),
      ]);
      await apiClient.post("/push/subscribe", { subscription: sub.toJSON(), user_agent: navigator.userAgent });
      setState("on");
      toast.success("Notifications activées sur cet appareil");
    } catch (err) {
      // Erreurs du navigateur (en anglais) remplacées par un message clair
      const msg = err?.response ? extractError(err)
        : (err?.message || "").startsWith("Le service") ? err.message
        : "L'inscription aux notifications a échoué sur ce navigateur. Vérifiez que les notifications sont autorisées pour ce site, puis réessayez.";
      toast.error(msg);
    } finally { setBusy(false); }
  };
  const disable = async () => {
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.getRegistration("/sw.js");
      const sub = await reg?.pushManager.getSubscription();
      if (sub) { await apiClient.post("/push/unsubscribe", { endpoint: sub.endpoint }); await sub.unsubscribe(); }
      setState("off");
      toast.success("Notifications désactivées sur cet appareil");
    } catch (err) { toast.error(extractError(err)); } finally { setBusy(false); }
  };
  const test = async () => {
    try { const { data } = await apiClient.post("/push/test"); toast.success(`Notification d'essai envoyée (${data.sent} appareil(s))`); }
    catch (err) { toast.error(extractError(err)); }
  };

  const text = {
    loading: "Vérification…",
    on: "Activées : vous êtes prévenu(e) sur cet appareil dès que le cabinet met un document à votre disposition.",
    off: "Soyez prévenu(e) sur cet appareil, même portail fermé, dès qu'un document est disponible.",
    denied: "Les notifications sont bloquées pour ce site dans les réglages du navigateur. Autorisez-les puis rechargez la page.",
    unsupported: "Ce navigateur ne prend pas en charge les notifications. WhatsApp et e-mail restent actifs.",
    "ios-install": "Sur iPhone : touchez Partager puis « Sur l'écran d'accueil », ouvrez le portail depuis l'icône ALBARKA, puis revenez ici.",
  }[state];

  return (
    <div className="albarka-card p-4 flex flex-wrap items-center gap-3" data-testid="push-optin" data-state={state}>
      {state === "on" ? <BellRing className="w-5 h-5 text-[#0F6B4A]" /> : state === "off" ? <Bell className="w-5 h-5 text-slate-500" /> : <BellOff className="w-5 h-5 text-slate-400" />}
      <div className="flex-1 min-w-[220px]">
        <div className="font-medium text-sm">Notifications sur cet appareil</div>
        <div className="text-xs text-muted-foreground">{text}</div>
      </div>
      {state === "off" && <Button size="sm" className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={enable} disabled={busy} data-testid="push-enable">Activer</Button>}
      {state === "on" && (
        <>
          <Button size="sm" variant="outline" onClick={test} data-testid="push-test">Tester</Button>
          <Button size="sm" variant="ghost" onClick={disable} disabled={busy} data-testid="push-disable">Désactiver</Button>
        </>
      )}
    </div>
  );
}
