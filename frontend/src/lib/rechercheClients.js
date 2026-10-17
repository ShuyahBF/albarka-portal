// Recherche dans la liste des clients (lot 29) : par nom de la SOCIÉTÉ, par numéro de TÉLÉPHONE (ou WhatsApp) ou par nom du RESPONSABLE.
// Pour un développeur WinDev : c'est l'équivalent d'une « recherche incrémentale » sur une table déjà chargée en mémoire.

// Minuscules, sans accents, espaces réduits : « Société Étoile » et « societe etoile » se retrouvent.
export function normaliserTexte(t) {
  return String(t || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
}

// Chiffres seuls d'un numéro : « +226 78 04 96 69 » et « 0022678049669 » deviennent comparables.
export function chiffres(t) {
  return String(t || "").replace(/\D/g, "");
}

// Garde les clients dont le nom de société, le nom du responsable, le téléphone ou le numéro WhatsApp correspond à TOUS les mots saisis.
// Un mot fait d'au moins 3 chiffres est cherché dans les numéros (sans tenir compte des espaces, du « + » ni du « 00 » initial).
export function filtrerClients(clients, saisie) {
  // Saisie faite SEULEMENT de chiffres, de « + », d'espaces et de tirets (« 78 04 96 69 », « +226-78049669 ») : c'est un NUMÉRO, cherché d'un bloc
  const tout = String(saisie || "");
  if (/^[\d+\-.\s()]+$/.test(tout) && chiffres(tout).length >= 3) {
    const d = chiffres(tout).replace(/^00/, "");
    return clients.filter((c) => [chiffres(c.phone), chiffres(c.whatsapp_number)].some((n) => n && n.includes(d)));
  }
  const mots = normaliserTexte(saisie).split(" ").filter(Boolean);
  if (mots.length === 0) return clients;
  return clients.filter((c) => {
    const texte = normaliserTexte(`${c.company || ""} ${c.full_name || ""}`);
    const numeros = [chiffres(c.phone), chiffres(c.whatsapp_number)].filter(Boolean);
    return mots.every((mot) => {
      if (texte.includes(mot)) return true;
      const d = chiffres(mot);
      // seulement si le mot est un numéro (pas « 3 » dans « Société 3 ») : au moins 3 chiffres et rien d'autre que des chiffres / + / espaces / tirets
      return d.length >= 3 && /^[\d+\-.\s()]+$/.test(mot) && numeros.some((n) => n.includes(d.replace(/^00/, "")));
    });
  });
}
