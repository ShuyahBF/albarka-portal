/*
  Service worker ALBARKA — notifications push (Web Push).
  Reçoit les notifications envoyées par le portail (albarka_push.py), même
  quand le portail est fermé, et ouvre la bonne page au clic.
*/
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

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
