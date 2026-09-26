/*
  Tableau de bord (cabinet) — les 10 derniers clients connectés, avec le début
  de la session, la dernière activité réelle (clavier, souris…) et la durée
  jusqu'à la fin de toute activité détectée. Visible de la Direction, du
  Secrétariat, du Superviseur et d'admin (API /presence/recent-clients).
*/
import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Activity } from "lucide-react";
import { apiClient } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { PresenceDot } from "@/components/Presence";

const ROLES = ["direction", "secretariat", "superviseur"];
const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—");
// Durée lisible : « 45 s », « 12 min », « 1 h 05 »
const fmtDuration = (s) => (s < 60 ? `${s} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${Math.floor(s / 3600)} h ${String(Math.round((s % 3600) / 60)).padStart(2, "0")}`);

export default function RecentClientsCard() {
  const { user } = useAuth();
  const roles = user?.roles || [];
  const allowed = roles.some((r) => ROLES.includes(r)) || (user?.email || "").toLowerCase() === "admin@sawalismartsystems.com";
  const [items, setItems] = useState(null);

  useEffect(() => {
    if (!allowed) return undefined;
    let alive = true;
    const load = () => apiClient.get("/presence/recent-clients", { params: { limit: 10 } })
      .then(({ data }) => { if (alive) setItems(data.items || []); }).catch(() => { if (alive) setItems([]); });
    load();
    const t = setInterval(load, 30000); // rafraîchi toutes les 30 s
    return () => { alive = false; clearInterval(t); };
  }, [allowed]);

  if (!allowed) return null;
  return (
    <div className="albarka-card p-5" data-testid="recent-clients-card">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-4 h-4 text-[#0F6B4A]" />
        <h2 className="font-display text-lg">Derniers clients connectés</h2>
      </div>
      {items === null ? <p className="text-sm text-muted-foreground">Chargement…</p> : items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Aucune connexion client enregistrée pour l'instant.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-muted-foreground border-b">
              <th className="py-2 pr-3">Client</th><th className="py-2 pr-3">Connecté le</th>
              <th className="py-2 pr-3">Dernière activité</th><th className="py-2 pr-3">Durée d'activité</th>
            </tr></thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.user_id} className="border-b last:border-0" data-testid={`recent-client-${c.user_id}`}>
                  <td className="py-2 pr-3">
                    <Link to={`/admin/clients/${c.user_id}`} className="inline-flex items-center gap-2 hover:text-[#0F6B4A]">
                      <PresenceDot presence={{ status: c.status, last_seen: c.last_seen }} />
                      <span className="font-medium">{c.name}</span>
                      {c.company && <span className="text-xs text-muted-foreground">· {c.company}</span>}
                    </Link>
                  </td>
                  <td className="py-2 pr-3 tabular-nums">{fmt(c.session_started_at)}</td>
                  <td className="py-2 pr-3 tabular-nums">{fmt(c.last_activity_at)}</td>
                  <td className="py-2 pr-3 tabular-nums font-medium">{fmtDuration(c.duration_seconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
