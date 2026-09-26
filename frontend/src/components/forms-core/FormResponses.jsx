/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  FormResponses : toutes les réponses d'un formulaire.
    - filtres : période, origine (invitation / lien public), recherche ;
    - tableau (date, répondant, origine + premières questions) ;
    - fiche détaillée d'une réponse : toutes les questions, tableaux,
      fichiers joints et signature ouverts par lien temporaire ;
    - suppression d'une réponse ; export CSV (Excel) de la sélection.

  Props : apiBase ("/forms"), form
*/
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Download, Search, Trash2, X, Paperclip, Loader2, Inbox } from "lucide-react";
import { apiClient } from "@/lib/api";
import { errorText, formatDateTime, readableValue, isVisible, downloadBlob } from "./fieldTypes";

const SOURCES = { invitation: "Invitation", public: "Lien public", portal: "Espace client" };

export default function FormResponses({ apiBase = "/forms", form }) {
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [source, setSource] = useState("all");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(null);

  const fields = useMemo(() => (form.pages || []).flatMap((p) => p.fields).filter((f) => f.type !== "section"), [form]);
  const params = () => ({ ...(dateFrom ? { date_from: dateFrom } : {}), ...(dateTo ? { date_to: dateTo } : {}) });

  const load = () => {
    setLoading(true);
    apiClient.get(`${apiBase}/${form.id}/submissions`, { params: params() })
      .then((r) => setData(r.data)).catch((e) => toast.error(errorText(e))).finally(() => setLoading(false));
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [form.id, dateFrom, dateTo]);

  const items = (data.items || []).filter((s) => (source === "all" || s.source === source) && (!query.trim() || JSON.stringify([s.respondent_name, s.respondent_email, s.data]).toLowerCase().includes(query.trim().toLowerCase())));
  const cols = fields.slice(0, 4);

  const remove = async (s) => {
    if (!window.confirm("Supprimer définitivement cette réponse ?")) return;
    try { await apiClient.delete(`${apiBase}/${form.id}/submissions/${s.id}`); setOpen(null); load(); toast.success("Réponse supprimée."); }
    catch (e) { toast.error(errorText(e)); }
  };
  const exportCsv = async () => {
    try {
      const q = new URLSearchParams(params()).toString();
      await downloadBlob(apiClient, `${apiBase}/${form.id}/export.csv${q ? `?${q}` : ""}`, `${form.number || "formulaire"}-reponses.csv`);
    } catch (e) { toast.error(errorText(e, "Export impossible")); }
  };
  // Ouverture d'un fichier joint (lien temporaire obtenu par le serveur).
  const openFile = async (fileId) => {
    // Onglet ouvert tout de suite (sinon bloqué par le navigateur), puis dirigé vers le lien temporaire.
    const win = window.open("about:blank", "_blank");
    try {
      const r = await apiClient.get(`${apiBase}/${form.id}/files/${fileId}`);
      let url = r.data.url;
      if (!url) {  // stockage sans lien temporaire : lecture du fichier par l'API
        const b = await apiClient.get(`${apiBase}/${form.id}/files/${fileId}/content`, { responseType: "blob" });
        url = URL.createObjectURL(b.data);
      }
      if (win) win.location.href = url; else window.location.href = url;
    } catch (e) { if (win) win.close(); toast.error(errorText(e, "Fichier indisponible")); }
  };

  return (
    <div className="space-y-3" data-testid="form-responses">
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-xs text-slate-600">Du<input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="block rounded-lg border border-slate-300 px-2 py-1.5 text-sm" /></label>
        <label className="text-xs text-slate-600">Au<input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="block rounded-lg border border-slate-300 px-2 py-1.5 text-sm" /></label>
        <select value={source} onChange={(e) => setSource(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
          <option value="all">Toutes origines</option><option value="invitation">Invitations</option><option value="public">Lien public</option>
        </select>
        <div className="relative flex-1 min-w-[180px]"><Search className="h-4 w-4 text-slate-400 absolute left-2.5 top-2.5" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher dans les réponses…" className="w-full rounded-lg border border-slate-300 pl-8 pr-3 py-1.5 text-sm" /></div>
        <button type="button" onClick={exportCsv} className="inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-sm" data-testid="responses-export"><Download className="h-4 w-4" /> Export Excel (CSV)</button>
      </div>
      <p className="text-xs text-slate-500">{items.length} réponse(s){items.length !== data.total ? ` sur ${data.total}` : ""}</p>
      {loading ? <p className="text-sm text-slate-500 inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</p> : items.length === 0 ? (
        <div className="text-center py-12 text-slate-400"><Inbox className="h-10 w-10 mx-auto mb-2" /><p className="text-sm">Aucune réponse pour l'instant.</p></div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500 text-left"><tr>
              <th className="px-3 py-2">Date</th><th className="px-3">Répondant</th><th className="px-3">Origine</th>
              {cols.map((f) => <th key={f.id} className="px-3 max-w-[180px] truncate">{f.label}</th>)}<th /></tr></thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.id} onClick={() => setOpen(s)} className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer" data-testid="response-row">
                  <td className="px-3 py-2 whitespace-nowrap text-xs">{formatDateTime(s.created_at)}{s.revisions ? <span className="text-slate-400"> (modifiée)</span> : null}</td>
                  <td className="px-3"><span className="font-medium">{s.respondent_name || "Anonyme"}</span><span className="block text-[11px] text-slate-400">{s.respondent_email}</span></td>
                  <td className="px-3 text-xs">{SOURCES[s.source] || s.source}</td>
                  {cols.map((f) => <td key={f.id} className="px-3 max-w-[180px] truncate text-xs">{readableValue(f, s.data?.[f.id])}</td>)}
                  <td className="px-2 text-right"><button type="button" onClick={(e) => { e.stopPropagation(); remove(s); }} className="p-1 text-slate-400 hover:text-rose-600" title="Supprimer"><Trash2 className="h-4 w-4" /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={(e) => e.target === e.currentTarget && setOpen(null)}>
          <div className="w-full max-w-2xl max-h-[88vh] overflow-y-auto rounded-2xl bg-white p-5 shadow-2xl" data-testid="response-detail">
            <div className="flex items-start justify-between mb-3">
              <div><h3 className="font-semibold">{open.respondent_name || "Réponse anonyme"}</h3>
                <p className="text-xs text-slate-500">{open.respondent_email} · {formatDateTime(open.created_at)} · {SOURCES[open.source] || open.source}</p></div>
              <button type="button" onClick={() => setOpen(null)} className="text-slate-400 hover:text-slate-700"><X className="h-5 w-5" /></button>
            </div>
            <dl className="divide-y divide-slate-100">
              {fields.filter((f) => isVisible(f, open.data || {})).map((f) => {
                const v = open.data?.[f.id];
                return (
                  <div key={f.id} className="py-2 grid grid-cols-1 sm:grid-cols-3 gap-1">
                    <dt className="text-xs font-medium text-slate-500">{f.label}</dt>
                    <dd className="sm:col-span-2 text-sm text-slate-800 whitespace-pre-line">
                      {v && typeof v === "object" && v.file_id ? (
                        <button type="button" onClick={() => openFile(v.file_id)} className="inline-flex items-center gap-1 text-primary underline"><Paperclip className="h-3.5 w-3.5" /> {f.type === "signature" ? "Voir la signature" : v.filename}</button>
                      ) : f.type === "table" && Array.isArray(v) ? (
                        <table className="text-xs border border-slate-200"><thead className="bg-slate-50"><tr>{(f.columns || []).map((c) => <th key={c.key} className="px-2 py-1 text-left">{c.label}</th>)}</tr></thead>
                          <tbody>{v.map((row, i) => <tr key={i} className="border-t">{(f.columns || []).map((c) => <td key={c.key} className="px-2 py-1">{row[c.key]}</td>)}</tr>)}</tbody></table>
                      ) : readableValue(f, v)}
                    </dd>
                  </div>
                );
              })}
            </dl>
            <div className="mt-4 flex justify-end"><button type="button" onClick={() => remove(open)} className="inline-flex items-center gap-1 text-sm text-rose-600"><Trash2 className="h-4 w-4" /> Supprimer cette réponse</button></div>
          </div>
        </div>
      )}
    </div>
  );
}
