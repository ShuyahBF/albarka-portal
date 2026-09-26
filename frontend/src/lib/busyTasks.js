// Tâches en cours — empêchent la déconnexion automatique pour inactivité.
//
// Une tâche est « en cours » tant que :
//   - une requête d'écriture vers l'API n'est pas terminée (POST/PUT/PATCH/
//     DELETE : envoi de fichier, génération de rapport, envoi WhatsApp…),
//     hors battements de présence ;
//   - ou un composant l'a déclarée avec beginTask() (ex. enregistrement d'une
//     note vocale dans le chat) et n'a pas encore appelé la fonction de fin.
// La minuterie d'inactivité s'abonne aux changements (subscribeBusy).
let count = 0;
const listeners = new Set();
const notify = () => listeners.forEach((fn) => { try { fn(count); } catch { /* ignoré */ } });

export function busyCount() { return count; }

export function subscribeBusy(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// Déclare une tâche ; renvoie la fonction à appeler quand elle est finie (une seule fois).
export function beginTask() {
  count += 1; notify();
  let done = false;
  return () => { if (!done) { done = true; count = Math.max(0, count - 1); notify(); } };
}

// Branche le suivi automatique des requêtes d'écriture sur le client axios.
let installed = false;
export function installBusyInterceptor(client) {
  if (installed) return;
  installed = true;
  const counts = (cfg) => cfg && cfg.method && cfg.method.toLowerCase() !== "get" && !String(cfg.url || "").includes("/presence/");
  client.interceptors.request.use((cfg) => { if (counts(cfg)) cfg.__endTask = beginTask(); return cfg; });
  client.interceptors.response.use(
    (res) => { res.config?.__endTask?.(); return res; },
    (err) => { err?.config?.__endTask?.(); return Promise.reject(err); },
  );
}
