/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  FormStats : statistiques d'un formulaire.
    - indicateurs : réponses, vues du lien, taux de conversion, taux de
      réponse aux invitations, première et dernière réponse ;
    - réponses par jour ;
    - UNE CARTE PAR QUESTION : barres par option (choix, oui/non, cases à
      cocher), moyenne/min/max/médiane et répartition des notes, dernières
      réponses pour les textes.

  Props : apiBase ("/forms"), form, color (couleur des graphiques, ex. "#0F6B4A")
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, BarChart, Bar, CartesianGrid } from "recharts";
import { apiClient } from "@/lib/api";
import { errorText, formatDateTime } from "./fieldTypes";

function Kpi({ label, value, hint }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-2xl font-semibold text-slate-900 tabular-nums">{value}</p>
      {hint && <p className="text-[11px] text-slate-400">{hint}</p>}
    </div>
  );
}

function QuestionCard({ q, color }) {
  const bars = q.options || q.distribution;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid={`stats-q-${q.id}`}>
      <p className="font-medium text-sm text-slate-900">{q.label}</p>
      <p className="text-[11px] text-slate-500 mb-2">{q.answered} réponse(s) · {q.answered_pct} % des répondants</p>
      {q.avg !== undefined && (
        <p className="text-sm mb-2">Moyenne <strong className="tabular-nums">{q.avg}</strong>
          <span className="text-slate-500"> · min {q.min} · médiane {q.median} · max {q.max}</span></p>
      )}
      {bars && bars.length > 0 && (
        <div style={{ height: Math.max(90, bars.length * 30) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bars} layout="vertical" margin={{ left: 4, right: 30 }}>
              <XAxis type="number" hide allowDecimals={false} />
              <YAxis type="category" dataKey="label" width={130} tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v, n, p) => [`${v}${p?.payload?.pct !== undefined ? ` (${p.payload.pct} %)` : ""}`, "Réponses"]} />
              <Bar dataKey="count" fill={color} radius={[0, 4, 4, 0]} label={{ position: "right", fontSize: 11, fill: "#475569" }} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
      {q.samples && (
        <ul className="space-y-1 text-sm text-slate-700">
          {q.samples.length ? q.samples.map((s, i) => <li key={i} className="border-l-2 border-slate-200 pl-2 line-clamp-2">{s}</li>)
            : <li className="text-slate-400 text-xs">Aucune réponse.</li>}
        </ul>
      )}
      {["file", "table"].includes(q.family) && <p className="text-xs text-slate-500">Consultez le détail dans l'onglet Réponses.</p>}
    </div>
  );
}

export default function FormStats({ apiBase = "/forms", form, color = "#0F6B4A" }) {
  const [st, setSt] = useState(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    setSt(null);
    apiClient.get(`${apiBase}/${form.id}/stats`, { params: { ...(dateFrom ? { date_from: dateFrom } : {}), ...(dateTo ? { date_to: dateTo } : {}) } })
      .then((r) => setSt(r.data)).catch((e) => toast.error(errorText(e)));
  }, [apiBase, form.id, dateFrom, dateTo]);

  if (!st) return <p className="text-sm text-slate-500 inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Calcul des statistiques…</p>;
  const inv = st.invitations || {};
  return (
    <div className="space-y-4" data-testid="form-stats">
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-slate-600">Du<input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="block rounded-lg border border-slate-300 px-2 py-1.5 text-sm" /></label>
        <label className="text-xs text-slate-600">Au<input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="block rounded-lg border border-slate-300 px-2 py-1.5 text-sm" /></label>
        {(dateFrom || dateTo) && <button type="button" onClick={() => { setDateFrom(""); setDateTo(""); }} className="text-xs text-primary">Toute la période</button>}
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Réponses" value={st.total_submissions} hint={st.last_at ? `dernière : ${formatDateTime(st.last_at)}` : "aucune pour l'instant"} />
        <Kpi label="Ouvertures du formulaire" value={st.views} hint={st.conversion_pct !== null ? `${st.conversion_pct} % ont répondu` : null} />
        <Kpi label="Invitations envoyées" value={inv.sent || 0} hint={`${inv.opened || 0} ouverte(s)`} />
        <Kpi label="Taux de réponse (invités)" value={`${inv.response_pct || 0} %`} hint={`${inv.answered || 0} réponse(s), ${inv.pending || 0} en attente`} />
      </div>
      {st.series.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-sm font-medium mb-2">Réponses par jour</p>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={st.series} margin={{ left: -20, right: 10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d) => d.slice(5).split("-").reverse().join("/")} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip labelFormatter={(d) => new Date(d).toLocaleDateString("fr-FR")} formatter={(v) => [v, "Réponses"]} />
                <Area type="monotone" dataKey="count" stroke={color} fill={color} fillOpacity={0.2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {st.questions.map((q) => <QuestionCard key={q.id} q={q} color={color} />)}
      </div>
      {st.questions.length === 0 && <p className="text-sm text-slate-400">Ce formulaire n'a pas encore de question.</p>}
    </div>
  );
}
