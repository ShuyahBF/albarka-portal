/*
  Lot 44 — Déconnexion programmée du portail (maintenance), vue de l'UTILISATEUR.
  Lit GET /maintenance/etat (route publique) et suit trois phases, calculées avec l'heure du SERVEUR :
    - annonce      : fenêtre fermable (une fois) + bandeau rouge avec le décompte ;
    - verrouillage : écran verrouillé, non fermable, décompte à la seconde ;
    - maintenance  : déconnexion forcée → retour à la page de connexion (connexion suspendue).
  Le super-admin n'est jamais verrouillé ni déconnecté : il voit seulement le bandeau (et gère depuis les Paramètres).
*/
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Lock, Wrench } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";

const ADMIN_ACCOUNT_EMAIL = "admin@sawalismartsystems.com";   // même compte que côté serveur (albarka_models.py)
const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

export default function MaintenancePortail() {
  const { user, logout } = useAuth();
  const superAdmin = (user?.email || "").toLowerCase() === ADMIN_ACCOUNT_EMAIL;
  const [etat, setEtat] = useState(null);
  const [reste, setReste] = useState(0);              // secondes restantes (décompte local recalé sur le serveur)
  const [annonceVue, setAnnonceVue] = useState(false);
  const decalage = useRef(0);                         // écart horloge serveur - horloge locale (ms)

  const lire = useCallback(async () => {
    try {
      const { data } = await apiClient.get("/maintenance/etat");
      decalage.current = new Date(data.maintenant_serveur).getTime() - Date.now();
      setEtat(data);
    } catch { /* réseau coupé : on garde le dernier état */ }
  }, []);

  // Relecture : toutes les 15 s, puis chaque seconde pendant le verrouillage pour ne jamais manquer l'échéance
  useEffect(() => {
    lire();
    const t = setInterval(lire, etat?.phase === "verrouillage" ? 3000 : 15000);
    return () => clearInterval(t);
  }, [lire, etat?.phase]);

  // Décompte à la seconde ; à l'échéance, déconnexion forcée (sauf super-admin)
  useEffect(() => {
    if (!etat?.active) return undefined;
    const tick = () => {
      const s = Math.max(0, Math.ceil((new Date(etat.echeance).getTime() - (Date.now() + decalage.current)) / 1000));
      setReste(s);
      if (s === 0 && !superAdmin) { logout(); window.location.href = "/login"; }
    };
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [etat, superAdmin, logout]);

  if (!etat?.active) return null;
  const verrouille = etat.phase !== "annonce" || (new Date(etat.debut_verrouillage).getTime() <= Date.now() + decalage.current);

  return (
    <>
      {/* Bandeau rouge permanent avec le décompte */}
      <div className="bg-rose-700 text-white text-sm px-4 py-2 flex items-center gap-2 print:hidden" role="alert" data-testid="maintenance-bandeau">
        <Wrench className="h-4 w-4 shrink-0" />
        <span className="min-w-0 flex-1 break-words">
          {superAdmin ? "Déconnexion programmée — " : "Maintenance — "}{etat.message} · déconnexion dans <b className="tabular-nums">{mmss(reste)}</b>
        </span>
      </div>

      {/* Annonce : fenêtre fermable une fois (utilisateurs autres que le super-admin) */}
      {!superAdmin && !verrouille && !annonceVue && (
        <div className="fixed inset-0 z-[70] bg-black/50 flex items-center justify-center p-4" data-testid="maintenance-annonce">
          <div className="bg-white rounded-2xl p-6 w-[calc(100%-2rem)] max-w-md max-h-[85dvh] overflow-y-auto space-y-3">
            <div className="flex items-center gap-2 font-semibold text-lg"><Wrench className="h-5 w-5 text-rose-700" /> Maintenance annoncée</div>
            <p className="text-sm whitespace-pre-line">{etat.message}</p>
            <p className="text-sm">Vous serez déconnecté dans <b className="tabular-nums">{mmss(reste)}</b>. Enregistrez votre travail.</p>
            <Button onClick={() => setAnnonceVue(true)} data-testid="maintenance-annonce-ok">J'ai compris</Button>
          </div>
        </div>
      )}

      {/* Verrouillage : écran bloqué, non fermable, décompte à la seconde */}
      {!superAdmin && verrouille && (
        <div className="fixed inset-0 z-[80] bg-slate-900/95 text-white flex items-center justify-center p-4" data-testid="maintenance-verrou">
          <div className="max-w-md w-[calc(100%-2rem)] text-center space-y-4">
            <Lock className="h-10 w-10 mx-auto text-rose-400" />
            <div className="text-lg font-semibold">Déconnexion imminente</div>
            <p className="text-sm whitespace-pre-line opacity-90">{etat.message}</p>
            <div className="text-5xl font-bold tabular-nums" data-testid="maintenance-decompte">{mmss(reste)}</div>
            <p className="text-xs opacity-70">Vous serez déconnecté automatiquement. Seul l'administrateur pourra rouvrir la connexion.</p>
          </div>
        </div>
      )}
    </>
  );
}
