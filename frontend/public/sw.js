/*
  Service worker ALBARKA — notifications push (Web Push).
  Reçoit les notifications envoyées par le portail (albarka_push.py), même
  quand le portail est fermé, et ouvre la bonne page au clic.
*/
// Application Android (TWA / PWABuilder) : quand l'ouverture d'une page échoue faute d'Internet, on affiche
// la page « Pas de connexion » (offline.html) au lieu de l'erreur du navigateur. Rien d'autre n'est mis en
// cache : le site reste toujours à jour (aucune ancienne version servie).
const CACHE_HORS_LIGNE = "albarka-hors-ligne-1";

// Installation : on garde de côté la seule page hors ligne, puis on s'active tout de suite
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_HORS_LIGNE).then((c) => c.add("/offline.html")).catch(() => {}));
  self.skipWaiting();
});

// Activation : prise de contrôle des pages ouvertes
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// Ouverture d'une page (navigation) : réseau d'abord ; en cas d'échec, page hors ligne
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match("/offline.html").then((r) => r || Response.error())),
  );
});

// Notification reçue : { title, body, url, tag }
self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data && event.data.text() }; }
  const title = data.title || "ALBARKA";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/favicon.svg",
    badge: "/favicon.svg",
    tag: data.tag || "albarka",
    renotify: true,
    data: { url: data.url || "/" },
  }));
});

// Clic : ouvre (ou ramène au premier plan) la page du portail concernée
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin).href;
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if (c.url.startsWith(self.location.origin)) { await c.focus(); if ("navigate" in c) await c.navigate(url); return; }
    }
    await self.clients.openWindow(url);
  })());
});
