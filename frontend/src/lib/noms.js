// noms.js — règle du 14/11/2026 : « NOM de famille » (TOUT en majuscules) + « Prénoms » (1re lettre de
// chaque mot en majuscule). Le « Nom complet » est la CONCATÉNATION des deux. Miroir de backend/albarka_noms.py
// (le serveur corrige de toute façon à l'enregistrement : ces fonctions servent à l'aperçu et au pré-remplissage).

/** Titres de civilité connus (liste déroulante). Même liste que backend/albarka_noms.py. */
export const TITRES = ["Mr", "Mme", "Mlle", "Dr", "Pr", "Me", "Ing.", "Arch.", "Hon.", "Sr", "Fr", "Abbé", "Père", "Pasteur",
  "Imam", "El Hadj", "Hadja", "Chef", "Mgr", "Cdt", "Col", "Gén.", "Lt", "Cpt"];

/** Titre : espaces nettoyés ; un titre connu reprend son écriture officielle (« mme » -> « Mme »). */
export function formaterTitre(titre) {
  const t = String(titre || "").trim().replace(/\s+/g, " ");
  return TITRES.find((x) => x.toLocaleLowerCase("fr-FR") === t.toLocaleLowerCase("fr-FR")) || t;
}

/** NOM de famille : espaces nettoyés, tout en majuscules. */
export function formaterNom(nom) {
  return String(nom || "").trim().replace(/\s+/g, " ").toLocaleUpperCase("fr-FR");
}

/** Prénoms : 1re lettre de chaque mot en majuscule, le reste en minuscules (Jean-Paul, N'Dour). */
export function formaterPrenoms(prenoms) {
  return String(prenoms || "").trim().replace(/\s+/g, " ").split(" ").filter(Boolean)
    .map((mot) => mot.toLocaleLowerCase("fr-FR").replace(/(^|[-'’])(\p{L})/gu, (_, sep, l) => sep + l.toLocaleUpperCase("fr-FR")))
    .join(" ");
}

/** Nom complet = Titre + NOM + Prénoms. */
export function assemblerNom(nom, prenoms, titre) {
  return [formaterTitre(titre), formaterNom(nom), formaterPrenoms(prenoms)].filter(Boolean).join(" ");
}

/** Si le Nom complet commence par un titre connu, le sépare : { titre, reste }. */
export function extraireTitre(nomComplet) {
  const texte = String(nomComplet || "").trim().replace(/\s+/g, " ");
  const t = [...TITRES].sort((a, b) => b.length - a.length)
    .find((x) => texte.toLocaleLowerCase("fr-FR").startsWith(x.toLocaleLowerCase("fr-FR") + " "));
  return t ? { titre: t, reste: texte.slice(t.length + 1) } : { titre: "", reste: texte };
}

/** Découpe un ancien « Nom complet » : les mots TOUT en majuscules du début = NOM ; sinon le 1er mot. */
export function separerNom(nomComplet) {
  const mots = String(nomComplet || "").trim().split(/\s+/).filter(Boolean);
  if (!mots.length) return { nom: "", prenoms: "" };
  let i = 0;
  while (i < mots.length && mots[i] === mots[i].toLocaleUpperCase("fr-FR") && /\p{L}/u.test(mots[i])) i += 1;
  if (i === 0) i = 1;
  return { nom: formaterNom(mots.slice(0, i).join(" ")), prenoms: formaterPrenoms(mots.slice(i).join(" ")) };
}

/** Valeurs de départ d'une fiche existante : champs enregistrés, sinon découpe du Nom complet. */
export function nomDepuisFiche(fiche) {
  if (fiche && (fiche.nom || fiche.prenoms)) return { titre: fiche.titre || "", nom: fiche.nom || "", prenoms: fiche.prenoms || "" };
  const { titre, reste } = extraireTitre(fiche && fiche.full_name);
  return { titre: (fiche && fiche.titre) || titre, ...separerNom(reste) };
}
