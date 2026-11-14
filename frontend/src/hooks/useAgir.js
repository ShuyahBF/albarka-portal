// useAgir — droits d'un CONTACT d'un client (lots 100-104) côté écran.
// Un contact se connecte au portail du client avec une FONCTION : pour chaque option (documents, missions…), « voir » et « agir ».
// `user.contact_nom` n'existe que pour un contact ; `user.contact_agir` = options où il peut agir. Le serveur refuse de toute façon une écriture non permise :
// ce hook sert à NE PAS AFFICHER les boutons d'action qu'il ne pourrait pas utiliser (pas de message de refus à découvrir).
import { useAuth } from "@/contexts/AuthContext";

export function useAgir() {
  const { user } = useAuth();
  const estContact = !!user?.contact_nom;
  // Un client ou un collaborateur (pas un contact) peut agir partout (ses propres droits s'appliquent ailleurs)
  const peutAgir = (option) => !estContact || (user.contact_agir || []).includes(option);
  return { estContact, peutAgir };
}
