import React, { useEffect, useState } from "react";
import { FileText, Briefcase, CalendarClock, AlertTriangle, Users, UserCog } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { toast } from "sonner";
import { useAuth } from "@/contexts/AuthContext";

function KPI({ icon: Icon, label, value, tone = "emerald", testid }) {
  const tones = {
    emerald: "bg-[#0F6B4A]/10 text-[#0F6B4A]",
    amber: "bg-[#E5A24B]/15 text-[#8A5A16]",
    danger: "bg-red-100 text-red-700",
    slate: "bg-slate-100 text-slate-700",
  };
  return (
    <div className="albarka-card p-5" data-testid={testid}>
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${tones[tone]}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="mt-4 font-display text-3xl font-semibold text-foreground">{value ?? "–"}</div>
      <div className="text-sm text-muted-foreground mt-1">{label}</div>
    </div>
  );
}

function BadgeStatus({ value }) {
  const map = {
    en_attente: "bg-slate-100 text-slate-700",
    en_cours: "bg-[#0F6B4A]/10 text-[#0F6B4A]",
    en_revue: "bg-blue-100 text-blue-700",
    terminee: "bg-emerald-100 text-emerald-800",
    archivee: "bg-slate-100 text-slate-500",
    a_venir: "bg-[#E5A24B]/15 text-[#8A5A16]",
    traitee: "bg-emerald-100 text-emerald-800",
    en_retard: "bg-red-100 text-red-700",
    recu: "bg-slate-100 text-slate-700",
    en_analyse: "bg-blue-100 text-blue-700",
    analyse: "bg-emerald-100 text-emerald-800",
    erreur_analyse: "bg-red-100 text-red-700",
  };
  return (
    <span className={`albarka-chip ${map[value] || "bg-slate-100 text-slate-700"}`}>
      {value?.replaceAll("_", " ") || "—"}
    </span>
  );
}

export function DashboardShared({ admin = false }) {
  const [summary, setSummary] = useState(null);
  const [activity, setActivity] = useState(null);
  const [loading, setLoading] = useState(true);
  const { user } = useAuth();

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const [s, a] = await Promise.all([
          apiClient.get("/dashboard/summary"),
          apiClient.get("/dashboard/activity"),
        ]);
        if (!mounted) return;
        setSummary(s.data);
        setActivity(a.data);
      } catch (err) {
        toast.error(extractError(err));
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, []);

  return (
    <div className="space-y-8" data-testid="dashboard-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">
          {admin ? "Vue cabinet" : "Vue client"}
        </div>
        <h1 className="font-display text-3xl md:text-4xl text-foreground">
          Bonjour {user?.full_name?.split(" ")[0]},
        </h1>
        <p className="text-muted-foreground mt-1">
          {admin
            ? "Voici l'état des dossiers et échéances de tous les clients."
            : "Voici l'état de vos pièces, missions et échéances."}
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPI icon={FileText} label="Pièces déposées" value={summary?.documents_total} tone="emerald" testid="kpi-docs" />
        <KPI icon={Briefcase} label="Missions en cours" value={summary?.missions_active} tone="amber" testid="kpi-missions" />
        <KPI icon={CalendarClock} label="Échéances à venir" value={summary?.echeances_upcoming} tone="slate" testid="kpi-echeances" />
        <KPI icon={AlertTriangle} label="Échéances en retard" value={summary?.echeances_late} tone="danger" testid="kpi-late" />
        {admin && (
          <>
            <KPI icon={Users} label="Clients" value={summary?.clients_total} tone="emerald" testid="kpi-clients" />
            <KPI icon={UserCog} label="Collaborateurs" value={summary?.staff_total} tone="slate" testid="kpi-staff" />
          </>
        )}
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="albarka-card p-6" data-testid="recent-echeances">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-display text-lg font-semibold">Échéances proches</h3>
            <CalendarClock className="w-4 h-4 text-muted-foreground" />
          </div>
          {loading && <div className="text-sm text-muted-foreground">Chargement…</div>}
          {!loading && (activity?.echeances || []).length === 0 && (
            <div className="text-sm text-muted-foreground">Aucune échéance enregistrée.</div>
          )}
          <ul className="space-y-3">
            {(activity?.echeances || []).slice(0, 5).map((e) => (
              <li key={e.id} className="flex items-start justify-between gap-3 py-2 border-b border-border last:border-b-0">
                <div>
                  <div className="text-sm font-medium">{e.title}</div>
                  <div className="text-xs text-muted-foreground">
                    {e.type?.toUpperCase()} · {e.due_date}
                  </div>
                </div>
                <BadgeStatus value={e.status} />
              </li>
            ))}
          </ul>
        </div>

        <div className="albarka-card p-6" data-testid="recent-documents">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-display text-lg font-semibold">Dernières pièces</h3>
            <FileText className="w-4 h-4 text-muted-foreground" />
          </div>
          {loading && <div className="text-sm text-muted-foreground">Chargement…</div>}
          {!loading && (activity?.documents || []).length === 0 && (
            <div className="text-sm text-muted-foreground">Aucune pièce déposée pour le moment.</div>
          )}
          <ul className="space-y-3">
            {(activity?.documents || []).slice(0, 5).map((d) => (
              <li key={d.id} className="flex items-start justify-between gap-3 py-2 border-b border-border last:border-b-0">
                <div>
                  <div className="text-sm font-medium truncate max-w-[220px]">{d.original_filename}</div>
                  <div className="text-xs text-muted-foreground">{d.kind?.replaceAll("_", " ")}</div>
                </div>
                <BadgeStatus value={d.status} />
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  return <DashboardShared admin={false} />;
}
