/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  FormStats : statistiques GRAPHIQUES d'un formulaire (1.2.0), animées et
  colorées, pour lire les données d'un coup d'œil :
    - barre de période (du … au …, raccourcis 7 j / 30 j / 90 j / 1 an / tout)
      et export Excel (CSV) de la période ;
    - 6 indicateurs colorés à chiffres animés (réponses, ouvertures,
      conversion, complétion moyenne, invitations, taux de réponse) ;
    - réponses dans le temps : barres par jour OU courbe cumulée ;
    - anneaux : provenance (lien public / invitation), identifiés / anonymes ;
    - entonnoir des invitations (envoyées → ouvertes → répondues) ;
    - jours de la semaine (barres) et heures de la journée (carte de chaleur) ;
    - meilleurs répondants et 10 dernières réponses ;
    - UNE CARTE PAR QUESTION : barres colorées ou camembert (au choix) pour
      les choix, anneau Oui/Non, note moyenne en étoiles + répartition,
      min / médiane / max pour les nombres, dernières réponses pour les textes.

  Props : apiBase ("/forms"), form, color (couleur principale du site, ex. "#0F6B4A")
*/
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  Loader2, Download, Eye, Inbox, TrendingUp, CheckCircle2, Send, Percent, CalendarDays, Clock,
  PieChart as PieIcon, Users, Trophy, History, Filter, BarChart3, Star, ListChecks,
} from "lucide-react";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, PieChart, Pie, Cell,
} from "recharts";
import { apiClient } from "@/lib/api";
import { errorText, formatDateTime, downloadBlob } from "./fieldTypes";
import { ui, cx } from "./ui";
import { PALETTE, ChartStyles, KpiCard, ChartCard, Meter, ChartTip } from "./charts";

// ---- Dates : aujourd'hui et « il y a n jours » au format AAAA-MM-JJ
const isoDay = (d) => d.toISOString().slice(0, 10);
const daysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return isoDay(d); };
// Libellé court d'une date AAAA-MM-JJ -> JJ/MM
const shortDay = (d) => (d || "").slice(5).split("-").reverse().join("/");
// Raccourcis de période (nombre de jours, null = toute la période)
const RANGES = [["7 j", 7], ["30 j", 30], ["90 j", 90], ["1 an", 365], ["Tout", null]];
// Nombre au format français (espaces des milliers, virgule décimale)
const fr = (v) => (typeof v === "number" ? v.toLocaleString("fr-FR", { maximumFractionDigits: 2 }) : v);
// Libellés de la provenance d'une réponse
const SOURCE_LABELS = { public: "Lien public", invitation: "Invitation", portal: "Portail" };

// Complète la série « réponses par jour » avec les jours sans réponse (à 0),
// pour que la courbe montre les creux ; ajoute le cumul pour la vue « Cumul ».
function fillSeries(series, dateFrom, dateTo) {
  if (!series.length) return [];
  const byDay = Object.fromEntries(series.map((p) => [p.date, p.count]));
  const start = new Date(`${dateFrom && dateFrom < series[0].date ? dateFrom : series[0].date}T00:00:00Z`);
  const lastData = series[series.length - 1].date;
  const end = new Date(`${dateTo && dateTo > lastData ? dateTo : lastData}T00:00:00Z`);
  const out = [];
  let total = 0;
  // 400 jours au plus : au-delà, on garde uniquement les jours avec réponses
  if ((end - start) / 86400000 > 400) return series.map((p) => ({ ...p, cumul: (total += p.count) }));
  for (let d = start; d <= end; d = new Date(d.getTime() + 86400000)) {
    const key = isoDay(d);
    const count = byDay[key] || 0;
    total += count;
    out.push({ date: key, count, cumul: total });
  }
  return out;
}

// Anneau (camembert évidé) avec le total au centre et une légende colorée
function Donut({ data, total, centerLabel, height = 180 }) {
  const shown = data.filter((d) => d.value > 0);
  return (
    <div>
      <div className="relative" style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={shown.length ? shown : [{ name: "Aucune", value: 1, color: "#E2E8F0" }]} dataKey="value" nameKey="name"
              innerRadius="62%" outerRadius="88%" paddingAngle={shown.length > 1 ? 3 : 0} stroke="none"
              animationDuration={900} animationBegin={150}>
              {(shown.length ? shown : [{ color: "#E2E8F0" }]).map((d, i) => <Cell key={i} fill={d.color} />)}
            </Pie>
            {shown.length > 0 && <Tooltip content={<ChartTip />} />}
          </PieChart>
        </ResponsiveContainer>
        {/* Total au centre de l'anneau */}
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-2xl font-display font-bold tabular-nums text-slate-900">{total}</span>
          <span className="text-[10px] uppercase tracking-wider text-slate-400">{centerLabel}</span>
        </div>
      </div>
      {/* Légende : pastille, libellé, nombre et pourcentage */}
      <ul className="mt-2 space-y-1">
        {data.map((d) => (
          <li key={d.name} className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-1.5 text-slate-600"><span className="h-2.5 w-2.5 rounded-full" style={{ background: d.color }} />{d.name}</span>
            <span className="tabular-nums text-slate-800 font-semibold">{d.value} <span className="text-slate-400 font-normal">({total ? Math.round((d.value * 100) / total) : 0} %)</span></span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Étoiles de la note moyenne (remplissage partiel de la dernière étoile)
function Stars({ value, max }) {
  return (
    <span className="inline-flex gap-0.5" aria-label={`${value} sur ${max}`}>
      {Array.from({ length: max }, (_, i) => {
        const fill = Math.max(0, Math.min(1, value - i));
        return (
          <span key={i} className="relative inline-block h-5 w-5">
            <Star className="absolute inset-0 h-5 w-5 text-slate-200" fill="currentColor" />
            <span className="absolute inset-0 overflow-hidden" style={{ width: `${fill * 100}%` }}>
              <Star className="h-5 w-5 text-amber-400" fill="currentColor" />
            </span>
          </span>
        );
      })}
    </span>
  );
}

// Carte d'une question : graphique adapté au type de question
function QuestionCard({ q, colors, delay }) {
  const bars = q.options || q.distribution;
  const isChoice = Boolean(q.options);
  // Vue « barres » ou « camembert » (choix) : camembert par défaut pour Oui/Non
  const [mode, setMode] = useState(q.family === "boolean" ? "pie" : "bars");
  const data = (bars || []).map((b, i) => ({
    ...b,
    // Oui en vert, Non en rouge ; sinon une couleur de la palette par option
    color: q.family === "boolean" ? (b.label === "Oui" ? "#10B981" : "#EF4444") : colors[i % colors.length],
  }));
  const isRating = q.type === "rating";
  const maxStars = isRating ? Math.max(1, (q.distribution || []).length) : 5;
  return (
    <ChartCard title={q.label} icon={isChoice ? ListChecks : q.avg !== undefined ? BarChart3 : History} color={colors[0]} delay={delay} testId={`stats-q-${q.id}`}
      subtitle={<span><span className={ui.badge.sky}>{q.answered_pct} %</span> {q.answered} réponse(s)</span>}
      right={isChoice && data.length > 0 ? (
        // Choix de la vue du graphique
        <div className="inline-flex rounded-lg ring-1 ring-slate-200 p-0.5 text-[11px]">
          {[["bars", "Barres"], ["pie", "Camembert"]].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setMode(k)} data-testid={`stats-q-${q.id}-${k}`}
              className={cx("px-2 py-0.5 rounded-md transition", mode === k ? "bg-slate-900 text-white" : "text-slate-500 hover:text-slate-900")}>{l}</button>
          ))}
        </div>
      ) : null}>
      {/* Nombres et notes : moyenne mise en avant + min / médiane / max */}
      {q.avg !== undefined && (
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <div className="rounded-lg bg-amber-50 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-amber-700 font-semibold">Moyenne</p>
            <p className="text-2xl font-display font-bold tabular-nums text-amber-700">{fr(q.avg)}</p>
          </div>
          {isRating && <Stars value={q.avg} max={maxStars} />}
          <div className="flex gap-1.5 text-[11px]">
            {[["min", q.min, "bg-sky-50 text-sky-700"], ["médiane", q.median, "bg-violet-50 text-violet-700"], ["max", q.max, "bg-emerald-50 text-emerald-700"]].map(([l, v, c]) => (
              <span key={l} className={cx("rounded-full px-2 py-0.5", c)}>{l} <strong className="tabular-nums">{fr(v)}</strong></span>
            ))}
          </div>
        </div>
      )}
      {/* Graphique des options / de la répartition des notes */}
      {data.length > 0 && (mode === "pie" && isChoice ? (
        <Donut data={data.map((d) => ({ name: d.label, value: d.count, color: d.color }))} total={q.answered} centerLabel="réponses" height={170} />
      ) : (
        <div style={{ height: Math.max(110, data.length * 34) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ left: 4, right: 36, top: 2, bottom: 2 }}>
              <XAxis type="number" hide allowDecimals={false} />
              <YAxis type="category" dataKey="label" width={130} tick={{ fontSize: 11, fill: "#475569" }} axisLine={false} tickLine={false} />
              <Tooltip cursor={{ fill: "#F1F5F9" }} content={<ChartTip />} />
              <Bar dataKey="count" name="Réponses" radius={[0, 6, 6, 0]} barSize={18} animationDuration={900}
                label={{ position: "right", fontSize: 11, fill: "#334155", formatter: (v) => v }}>
                {data.map((d, i) => <Cell key={i} fill={d.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      ))}
      {/* Textes et dates : dernières réponses en bulles */}
      {q.samples && (
        <ul className="space-y-1.5 text-sm text-slate-700">
          {q.samples.length ? q.samples.map((s, i) => (
            <li key={i} className="rounded-lg bg-slate-50 px-3 py-1.5 line-clamp-2 border-l-4" style={{ borderColor: colors[i % colors.length] }}>{s}</li>
          )) : <li className="text-slate-400 text-xs italic">Aucune réponse.</li>}
        </ul>
      )}
      {["file", "table"].includes(q.family) && <p className="text-xs text-slate-500">Consultez le détail dans l'onglet Réponses.</p>}
    </ChartCard>
  );
}

export default function FormStats({ apiBase = "/forms", form, color = "#0F6B4A" }) {
  const [st, setSt] = useState(null);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [range, setRange] = useState("Tout");          // raccourci de période actif
  const [timeMode, setTimeMode] = useState("day");     // "day" = par jour, "cumul" = cumulé
  // Couleurs : la couleur du site d'abord, puis la palette vive
  const colors = useMemo(() => [color, ...PALETTE.filter((c) => c.toLowerCase() !== color.toLowerCase())], [color]);

  // Chargement des statistiques à chaque changement de période
  useEffect(() => {
    setSt(null);
    apiClient.get(`${apiBase}/${form.id}/stats`, { params: { ...(dateFrom ? { date_from: dateFrom } : {}), ...(dateTo ? { date_to: dateTo } : {}) } })
      .then((r) => setSt(r.data)).catch((e) => toast.error(errorText(e)));
  }, [apiBase, form.id, dateFrom, dateTo]);

  // Raccourci de période : 7 j, 30 j… ou toute la période
  const applyRange = (label, n) => {
    setRange(label);
    setDateFrom(n ? daysAgo(n) : "");
    setDateTo(n ? isoDay(new Date()) : "");
  };

  // Export Excel (CSV) des réponses de la période affichée
  const exportCsv = async () => {
    try {
      const q = new URLSearchParams({ ...(dateFrom ? { date_from: dateFrom } : {}), ...(dateTo ? { date_to: dateTo } : {}) }).toString();
      await downloadBlob(apiClient, `${apiBase}/${form.id}/export.csv${q ? `?${q}` : ""}`, `${form.number || "formulaire"}-reponses.csv`);
    } catch (e) { toast.error(errorText(e)); }
  };

  const series = useMemo(() => (st ? fillSeries(st.series || [], dateFrom, dateTo) : []), [st, dateFrom, dateTo]);

  // Barre de période (toujours visible, même pendant le chargement)
  const toolbar = (
    <div className={cx(ui.card, "flex flex-wrap items-end gap-3 shadow-sm")} data-testid="stats-toolbar">
      <label className="block"><span className={ui.label}>Du</span>
        <input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setRange(""); }} className={ui.inputInline} data-testid="stats-from" /></label>
      <label className="block"><span className={ui.label}>Au</span>
        <input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setRange(""); }} className={ui.inputInline} data-testid="stats-to" /></label>
      <div className="flex flex-wrap gap-1.5" data-testid="stats-ranges">
        {RANGES.map(([label, n]) => (
          <button key={label} type="button" onClick={() => applyRange(label, n)} className={ui.chip(range === label)} data-testid={`stats-range-${n || "all"}`}>{label}</button>
        ))}
      </div>
      <button type="button" onClick={exportCsv} className={cx(ui.act.emerald, "ml-auto")} data-testid="stats-export"><Download className="h-3.5 w-3.5" /> Export Excel (CSV)</button>
    </div>
  );

  if (!st) {
    return (
      <div className="space-y-4">
        {toolbar}
        <p className={ui.loading}><Loader2 className="h-4 w-4 animate-spin inline mr-1" /> Calcul des statistiques…</p>
      </div>
    );
  }

  const inv = st.invitations || {};
  const total = st.total_submissions;
  // Provenance des réponses (lien public, invitation…) pour l'anneau
  const sources = (st.by_source || []).map((s, i) => ({ name: SOURCE_LABELS[s.source] || s.source, value: s.count, color: [colors[0], "#F59E0B", "#0EA5E9", "#8B5CF6"][i % 4] }));
  const who = [{ name: "Identifiés", value: st.identified || 0, color: "#6366F1" }, { name: "Anonymes", value: st.anonymous || 0, color: "#CBD5E1" }];
  // Heures : intensité de la couleur proportionnelle au nombre de réponses
  const maxHour = Math.max(1, ...(st.by_hour || []).map((h) => h.count));
  const peakHour = (st.by_hour || []).reduce((a, h) => (h.count > (a?.count || 0) ? h : a), null);
  const peakDay = (st.by_weekday || []).reduce((a, d) => (d.count > (a?.count || 0) ? d : a), null);
  const maxTop = Math.max(1, ...(st.top_respondents || []).map((r) => r.count));
  const rankColors = ["#F59E0B", "#94A3B8", "#B45309"];   // or, argent, bronze

  return (
    <div className="space-y-4" data-testid="form-stats">
      <ChartStyles />
      {toolbar}

      {/* 1. Indicateurs colorés à chiffres animés */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3" data-testid="stats-kpis">
        <KpiCard label="Réponses" value={total} icon={Inbox} theme="indigo" delay={0} testId="stats-kpi-total"
          hint={st.last_at ? `dernière : ${formatDateTime(st.last_at)}` : "aucune pour l'instant"} />
        <KpiCard label="Ouvertures" value={st.views} icon={Eye} theme="sky" delay={60} hint="du formulaire (lien public)" />
        <KpiCard label="Conversion" value={st.conversion_pct ?? 0} decimals={st.conversion_pct % 1 ? 1 : 0} suffix=" %" icon={TrendingUp} theme="emerald" delay={120} hint="ouvertures → réponses" />
        <KpiCard label="Complétion" value={st.completion_pct || 0} decimals={(st.completion_pct || 0) % 1 ? 1 : 0} suffix=" %" icon={CheckCircle2} theme="amber" delay={180} hint="questions remplies en moyenne" />
        <KpiCard label="Invitations" value={inv.sent || 0} icon={Send} theme="violet" delay={240} hint={`${inv.opened || 0} ouverte(s)`} />
        <KpiCard label="Taux de réponse" value={inv.response_pct || 0} decimals={(inv.response_pct || 0) % 1 ? 1 : 0} suffix=" %" icon={Percent} theme="rose" delay={300} hint={`${inv.pending || 0} invité(s) en attente`} />
      </div>

      {/* 2. Réponses dans le temps : barres par jour ou courbe cumulée */}
      <ChartCard title="Réponses dans le temps" icon={CalendarDays} color={colors[0]} delay={100} testId="stats-timeline"
        subtitle={total ? `${total} réponse(s) sur ${st.active_days} jour(s) actif(s)${peakDay?.count ? ` · jour le plus actif : ${peakDay.day}` : ""}` : "Aucune réponse sur la période."}
        right={
          <div className="inline-flex rounded-lg ring-1 ring-slate-200 p-0.5 text-[11px]">
            {[["day", "Par jour"], ["cumul", "Cumul"]].map(([k, l]) => (
              <button key={k} type="button" onClick={() => setTimeMode(k)} data-testid={`stats-time-${k}`}
                className={cx("px-2 py-0.5 rounded-md transition", timeMode === k ? "bg-slate-900 text-white" : "text-slate-500 hover:text-slate-900")}>{l}</button>
            ))}
          </div>
        }>
        <div className="h-60">
          {series.length === 0 ? <p className={ui.empty}>Pas encore de réponse à afficher.</p> : (
            <ResponsiveContainer width="100%" height="100%">
              {timeMode === "day" ? (
                <BarChart data={series} margin={{ left: -18, right: 8, top: 8 }}>
                  <defs>
                    {/* Dégradé vertical des barres, aux couleurs du site */}
                    <linearGradient id="fcBarGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={colors[0]} stopOpacity={1} />
                      <stop offset="100%" stopColor={colors[0]} stopOpacity={0.45} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#64748B" }} tickFormatter={shortDay} minTickGap={16} axisLine={false} tickLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748B" }} axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: "#F1F5F9" }} content={<ChartTip labelFormatter={(d) => new Date(d).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })} />} />
                  <Bar dataKey="count" name="Réponses" fill="url(#fcBarGrad)" radius={[6, 6, 0, 0]} maxBarSize={36} animationDuration={900} />
                </BarChart>
              ) : (
                <AreaChart data={series} margin={{ left: -18, right: 8, top: 8 }}>
                  <defs>
                    <linearGradient id="fcAreaGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#6366F1" stopOpacity={0.45} />
                      <stop offset="100%" stopColor="#6366F1" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#64748B" }} tickFormatter={shortDay} minTickGap={16} axisLine={false} tickLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748B" }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTip labelFormatter={(d) => new Date(d).toLocaleDateString("fr-FR")} unit="réponse(s) au total" />} />
                  <Area type="monotone" dataKey="cumul" name="Cumul" stroke="#6366F1" strokeWidth={2.5} fill="url(#fcAreaGrad)" animationDuration={1100} />
                </AreaChart>
              )}
            </ResponsiveContainer>
          )}
        </div>
      </ChartCard>

      {/* 3. Anneaux (provenance, identifiés) et entonnoir des invitations */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <ChartCard title="Provenance" subtitle="Par où les réponses arrivent." icon={PieIcon} color="#F59E0B" delay={150} testId="stats-sources">
          <Donut data={sources.length ? sources : [{ name: "Aucune", value: 0, color: "#E2E8F0" }]} total={total} centerLabel="réponses" />
        </ChartCard>
        <ChartCard title="Identifiés vs anonymes" subtitle="Répondants ayant donné leur nom ou e-mail." icon={Users} color="#6366F1" delay={200} testId="stats-who">
          <Donut data={who} total={total} centerLabel="réponses" />
        </ChartCard>
        <ChartCard title="Entonnoir des invitations" subtitle="De l'envoi à la réponse." icon={Filter} color="#8B5CF6" delay={250} testId="stats-funnel">
          {inv.sent ? (
            <div className="space-y-4 pt-2">
              <Meter label="Envoyées" value={inv.sent} pct={100} color="#8B5CF6" />
              <Meter label="Ouvertes" value={inv.opened} pct={inv.open_pct} sub={`${inv.open_pct} %`} color="#0EA5E9" />
              <Meter label="Répondues" value={inv.answered} pct={inv.response_pct} sub={`${inv.response_pct} %`} color="#10B981" />
              <Meter label="En attente" value={inv.pending} pct={inv.sent ? (inv.pending * 100) / inv.sent : 0} color="#F59E0B" />
            </div>
          ) : <p className={ui.empty}>Aucune invitation envoyée.</p>}
        </ChartCard>
      </div>

      {/* 4. Quand répond-on ? Jours de la semaine et heures de la journée */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Jours de la semaine" subtitle={peakDay?.count ? `Le ${peakDay.day.toLowerCase()}. est le jour le plus actif.` : "Répartition des réponses par jour."} icon={CalendarDays} color="#0EA5E9" delay={200} testId="stats-weekday">
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={st.by_weekday || []} margin={{ left: -22, right: 4, top: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#64748B" }} axisLine={false} tickLine={false} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748B" }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "#F1F5F9" }} content={<ChartTip />} />
                <Bar dataKey="count" name="Réponses" radius={[6, 6, 0, 0]} maxBarSize={40} animationDuration={900}>
                  {(st.by_weekday || []).map((d, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
        <ChartCard title="Heures de la journée" subtitle={peakHour?.count ? `Pic d'activité vers ${peakHour.hour} h.` : "Carte de chaleur des réponses par heure."} icon={Clock} color="#EF4444" delay={250} testId="stats-hours">
          {/* Carte de chaleur : 24 cases, plus la case est foncée, plus il y a de réponses */}
          <div className="grid grid-cols-12 gap-1.5 pt-2">
            {(st.by_hour || []).map((h) => (
              <div key={h.hour} className="group relative" title={`${h.hour} h : ${h.count} réponse(s)`}>
                <div className="h-10 rounded-md ring-1 ring-slate-100 transition-transform group-hover:scale-110"
                  style={{ background: h.count ? colors[0] : "#F1F5F9", opacity: h.count ? 0.25 + 0.75 * (h.count / maxHour) : 1 }} />
                <p className="text-[9px] text-center text-slate-400 mt-0.5 tabular-nums">{h.hour}h</p>
              </div>
            ))}
          </div>
          <div className="flex items-center justify-end gap-1.5 text-[10px] text-slate-400 mt-2">
            moins {[0.25, 0.5, 0.75, 1].map((o) => <span key={o} className="h-2.5 w-4 rounded-sm" style={{ background: colors[0], opacity: o }} />)} plus
          </div>
        </ChartCard>
      </div>

      {/* 5. Meilleurs répondants et dernières réponses */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Meilleurs répondants" subtitle="Classement par nombre de réponses." icon={Trophy} color="#F59E0B" delay={250} testId="stats-top">
          {(st.top_respondents || []).length === 0 ? <p className={ui.empty}>Aucun répondant identifié.</p> : (
            <div className="space-y-3">
              {st.top_respondents.map((r, i) => (
                <div key={r.label} className="flex items-center gap-2">
                  {/* Rang : médaille or / argent / bronze pour les 3 premiers */}
                  <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
                    style={{ background: rankColors[i] || "#CBD5E1" }}>{i + 1}</span>
                  <div className="flex-1 min-w-0"><Meter label={r.label} value={r.count} pct={(r.count * 100) / maxTop} color={colors[i % colors.length]} /></div>
                </div>
              ))}
            </div>
          )}
        </ChartCard>
        <ChartCard title="10 dernières réponses" icon={History} color={colors[0]} delay={300} testId="stats-recent">
          {(st.recent || []).length === 0 ? <p className={ui.empty}>Aucune réponse.</p> : (
            <ul className="divide-y divide-slate-100">
              {st.recent.map((r, i) => (
                <li key={r.id || i} className="flex items-center justify-between gap-2 py-1.5 text-xs">
                  <span className="flex items-center gap-2 min-w-0">
                    {/* Initiale du répondant dans une pastille colorée */}
                    <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white"
                      style={{ background: r.label ? colors[i % colors.length] : "#CBD5E1" }}>{(r.label || "?").charAt(0).toUpperCase()}</span>
                    <span className="truncate text-slate-700 font-medium">{r.label || "Anonyme"}</span>
                    <span className={r.source === "invitation" ? ui.badge.violet : ui.badge.amber}>{SOURCE_LABELS[r.source] || r.source}</span>
                  </span>
                  <span className="text-slate-400 tabular-nums shrink-0">{formatDateTime(r.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </ChartCard>
      </div>

      {/* 6. Une carte par question */}
      {st.questions.length > 0 && <p className={cx(ui.eyebrow, "pt-2")}>Analyse question par question</p>}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {st.questions.map((q, i) => <QuestionCard key={q.id} q={q} colors={colors} delay={Math.min(i, 8) * 50} />)}
      </div>
      {st.questions.length === 0 && <p className={ui.empty}>Ce formulaire n'a pas encore de question.</p>}
    </div>
  );
}
