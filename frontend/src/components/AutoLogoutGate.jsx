/*
  Déconnexion automatique pour inactivité — repris de Sawali (AutoLogoutGate).
  Monté dans PortalLayout (espace client et cabinet). Lit le délai réglé par
  le superviseur (Paramètres → Cabinet, GET /me/idle-config), affiche un
  avertissement 30 s avant, puis déconnecte (présence « hors ligne » envoyée).
  Jamais pendant une tâche en cours (envoi, enregistrement…) : busyTasks.js.
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Clock, LogOut } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { useIdleTimer } from "@/lib/useIdleTimer";
import { installBusyInterceptor } from "@/lib/busyTasks";
import { sendOffline } from "@/components/Presence";

// Suivi automatique des requêtes d'écriture en cours (une seule fois)
installBusyInterceptor(apiClient);

export default function AutoLogoutGate() {
  const { user, logout } = useAuth() || {};
  const [config, setConfig] = useState({ auto_logout_minutes: 0, warning_seconds: 30 });

  // Délai lu à la connexion
  useEffect(() => {
    if (!user) { setConfig({ auto_logout_minutes: 0, warning_seconds: 30 }); return undefined; }
    let cancelled = false;
    apiClient.get("/me/idle-config").then((r) => { if (!cancelled) setConfig(r.data); }).catch(() => { /* désactivée par défaut */ });
    return () => { cancelled = true; };
  }, [user]);

  const handleLogout = async () => {
    await sendOffline(); // hors ligne tout de suite pour le cabinet
    try { logout && logout(); } catch { /* ignoré */ }
    toast.warning("Session fermée après une période d'inactivité — merci de vous reconnecter.", { duration: 6000, id: "idle-logout-toast" });
    // Navigation complète : ferme toutes les fenêtres encore ouvertes
    window.location.assign("/login");
  };

  const { warningCountdown, stayConnected } = useIdleTimer({
    idleMinutes: Number(config.auto_logout_minutes) || 0,
    warningSeconds: Number(config.warning_seconds) || 30,
    onLogout: handleLogout,
    enabled: !!user,
  });

  if (warningCountdown === null) return null;
  return (
    <div className="fixed inset-0 z-[9999] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      role="alertdialog" aria-modal="true" aria-labelledby="idle-warning-title" data-testid="idle-warning-modal">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
        <div className="flex items-center gap-3 mb-3">
          <div className="h-12 w-12 rounded-full bg-amber-50 flex items-center justify-center">
            <Clock className="h-6 w-6 text-[#B45309] animate-pulse" />
          </div>
          <div>
            <h2 id="idle-warning-title" className="font-display text-lg text-slate-900">Session bientôt fermée</h2>
            <p className="text-xs text-slate-500">Aucune activité détectée</p>
          </div>
        </div>
        <p className="text-sm text-slate-700">
          Vous allez être déconnecté(e) dans{" "}
          <strong className="text-[#B45309] tabular-nums" data-testid="idle-warning-countdown">{warningCountdown}</strong>{" "}
          seconde{warningCountdown > 1 ? "s" : ""} faute d'activité.
        </p>
        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 mt-5">
          <button onClick={handleLogout} className="text-xs inline-flex items-center justify-center gap-1.5 rounded-lg border border-slate-300 hover:bg-slate-50 text-slate-700 px-3 py-2" data-testid="idle-warning-logout-now">
            <LogOut className="h-3.5 w-3.5" /> Se déconnecter maintenant
          </button>
          <button onClick={stayConnected} className="text-sm rounded-lg bg-[#0F6B4A] hover:bg-[#0A4E36] text-white px-4 py-2 font-semibold" data-testid="idle-warning-stay">
            Rester connecté(e)
          </button>
        </div>
      </div>
    </div>
  );
}
