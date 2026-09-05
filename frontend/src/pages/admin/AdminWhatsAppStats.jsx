import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  BarChart3, MessageCircle, Clock, ArrowLeft, Users, RefreshCw, ArrowUpRight, ArrowDownLeft,
} from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const TYPE_LABELS = {
  text: "Texte", image: "Photo", audio: "Note vocale", video: "Vidéo",
  document: "Document", location: "Localisation", unknown: "Autre",
};

function fmtSec(s) {
  if (s == null) return "—";
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return `${h} h ${m.toString().padStart(2, "0")}`;
}

function currentYearMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${(d.getMonth() + 1).toString().padStart(2, "0")}`;
}

export default function AdminWhatsAppStats() {
  const navigate = useNavigate();
  const [yearMonth, setYearMonth] = useState(currentYearMonth());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/whatsapp/stats", { params: { year_month: yearMonth } });
      setData(data);
    } catch (err) { toast.error(extractError(err)); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [yearMonth]);

  const maxDaily = useMemo(() => {
    if (!data?.daily?.length) return 1;
    return Math.max(...data.daily.map((d) => (d.inbound || 0) + (d.outbound || 0)), 1);
  }, [data]);

  return (
    <div className="space-y-4" data-testid="wa-stats-page">
      <div className="flex items-center gap-2 flex-wrap">
        <Button variant="ghost" size="sm" onClick={() => navigate("/admin/whatsapp")} data-testid="wa-stats-back-btn">
          <ArrowLeft className="w-4 h-4 mr-1" /> Retour
        </Button>
        <div className="flex-1">
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-[#0F6B4A]" />
            Statistiques Communication WhatsApp
          </h1>
          <p className="text-sm text-muted-foreground">Volume mensuel, temps de réponse et top contacts.</p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            type="month"
            value={yearMonth}
            onChange={(e) => setYearMonth(e.target.value)}
            className="w-40"
            data-testid="wa-stats-month-input"
          />
          <Button variant="outline" size="sm" onClick={load} disabled={loading} data-testid="wa-stats-refresh-btn">
            <RefreshCw className={`w-4 h-4 mr-1 ${loading ? "animate-spin" : ""}`} /> Rafraîchir
          </Button>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card data-testid="wa-stats-kpi-inbound">
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground flex items-center gap-1"><ArrowDownLeft className="w-3 h-3" />Reçus</CardTitle></CardHeader>
          <CardContent><div className="text-2xl font-semibold">{data?.inbound ?? "—"}</div></CardContent>
        </Card>
        <Card data-testid="wa-stats-kpi-outbound">
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground flex items-center gap-1"><ArrowUpRight className="w-3 h-3" />Envoyés</CardTitle></CardHeader>
          <CardContent><div className="text-2xl font-semibold">{data?.outbound ?? "—"}</div></CardContent>
        </Card>
        <Card data-testid="wa-stats-kpi-avg">
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground flex items-center gap-1"><Clock className="w-3 h-3" />Temps de réponse moyen</CardTitle></CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{fmtSec(data?.avg_response_seconds)}</div>
            <div className="text-[10px] text-muted-foreground">Médiane : {fmtSec(data?.median_response_seconds)} · sur {data?.response_samples || 0} échantillons</div>
          </CardContent>
        </Card>
        <Card data-testid="wa-stats-kpi-total">
          <CardHeader className="pb-2"><CardTitle className="text-xs text-muted-foreground flex items-center gap-1"><MessageCircle className="w-3 h-3" />Volume total</CardTitle></CardHeader>
          <CardContent><div className="text-2xl font-semibold">{data?.total ?? "—"}</div></CardContent>
        </Card>
      </div>

      {/* Types de messages entrants */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card data-testid="wa-stats-types">
          <CardHeader><CardTitle className="text-sm">Types de messages entrants</CardTitle></CardHeader>
          <CardContent>
            {(!data?.types || data.types.length === 0) && (
              <div className="text-sm text-muted-foreground">Aucun message ce mois-ci.</div>
            )}
            <div className="space-y-2">
              {data?.types?.map((t) => {
                const pct = data.inbound > 0 ? Math.round((t.n / data.inbound) * 100) : 0;
                return (
                  <div key={t.type} data-testid={`wa-stats-type-${t.type}`}>
                    <div className="flex justify-between text-xs mb-0.5">
                      <span>{TYPE_LABELS[t.type] || t.type}</span>
                      <span className="text-muted-foreground">{t.n} · {pct}%</span>
                    </div>
                    <div className="h-2 rounded bg-slate-100 overflow-hidden">
                      <div className="h-full bg-[#0F6B4A]" style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        <Card data-testid="wa-stats-top">
          <CardHeader><CardTitle className="text-sm flex items-center gap-2"><Users className="w-4 h-4" />Top contacts (entrants)</CardTitle></CardHeader>
          <CardContent>
            {(!data?.top_contacts || data.top_contacts.length === 0) && (
              <div className="text-sm text-muted-foreground">Aucun contact ce mois-ci.</div>
            )}
            <ol className="space-y-1.5">
              {data?.top_contacts?.map((c, i) => (
                <li key={c.phone} className="flex items-center gap-2 text-sm" data-testid={`wa-stats-top-${c.phone}`}>
                  <span className="w-5 text-right text-muted-foreground text-xs">#{i + 1}</span>
                  <span className="flex-1 truncate">
                    <span className="font-medium">{c.name || c.phone}</span>
                    {c.name && <span className="text-muted-foreground text-xs ml-1">({c.phone})</span>}
                  </span>
                  <span className="text-xs font-mono bg-slate-100 px-1.5 py-0.5 rounded">{c.count}</span>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>

      {/* Séries journalières */}
      <Card data-testid="wa-stats-daily">
        <CardHeader><CardTitle className="text-sm">Volume par jour</CardTitle></CardHeader>
        <CardContent>
          {(!data?.daily || data.daily.length === 0) && (
            <div className="text-sm text-muted-foreground">Pas de données pour ce mois.</div>
          )}
          {data?.daily?.length > 0 && (
            <div className="flex items-end gap-1 h-40" role="img" aria-label="Volume par jour">
              {data.daily.map((d) => {
                const total = (d.inbound || 0) + (d.outbound || 0);
                const inH = maxDaily ? ((d.inbound || 0) / maxDaily) * 100 : 0;
                const outH = maxDaily ? ((d.outbound || 0) / maxDaily) * 100 : 0;
                return (
                  <div key={d.day} className="flex-1 flex flex-col items-center gap-0.5 group" title={`${d.day} · reçus ${d.inbound || 0} · envoyés ${d.outbound || 0}`}>
                    <div className="w-full flex flex-col-reverse gap-px" style={{ height: "80%" }}>
                      <div className="bg-[#0F6B4A]" style={{ height: `${inH}%` }} />
                      <div className="bg-[#E5A24B]" style={{ height: `${outH}%` }} />
                    </div>
                    <div className="text-[9px] text-muted-foreground rotate-0">{d.day.slice(8)}</div>
                  </div>
                );
              })}
            </div>
          )}
          <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
            <div className="flex items-center gap-1"><span className="inline-block w-3 h-3 bg-[#0F6B4A] rounded-sm" /> Reçus</div>
            <div className="flex items-center gap-1"><span className="inline-block w-3 h-3 bg-[#E5A24B] rounded-sm" /> Envoyés</div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
