// Identifiant de cet appareil (navigateur) pour la liste blanche du personnel.
// Généré une fois et gardé dans le navigateur ; effacer les données du site
// oblige à refaire autoriser l'appareil par le superviseur.
const KEY = "albarka_device_id";

export function getDeviceId() {
  try {
    let id = localStorage.getItem(KEY);
    if (!id) {
      id = (window.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`);
      localStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    return null; // stockage bloqué : l'appareil ne peut pas être reconnu
  }
}

// Code d'accès temporaire reçu par e-mail / WhatsApp (lien /login?acces=CODE)
const CODE_KEY = "albarka_access_code";
export function saveAccessCode(code) { try { sessionStorage.setItem(CODE_KEY, code); } catch { /* ignoré */ } }
export function getAccessCode() { try { return sessionStorage.getItem(CODE_KEY) || null; } catch { return null; } }
export function clearAccessCode() { try { sessionStorage.removeItem(CODE_KEY); } catch { /* ignoré */ } }
