/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  FormSendPanel : diffusion d'un formulaire et suivi.
    1. Envoyer à des destinataires choisis (clients du site) par e-mail et/ou
       WhatsApp, avec un message personnalisé : chaque destinataire reçoit SON
       lien (on sait qui a ouvert et qui a répondu) ;
    2. Lien public pour les non-clients : activer, copier, QR code, nouveau
       lien (l'ancien cesse de fonctionner), désactiver ;
    3. Suivi des envois : statut (envoyé, ouvert, répondu, désactivé), détail
       des canaux, relance des non-répondants, désactivation d'un lien.

  Props : apiBase ("/forms"), form, onChanged(), publicPath ("/f" : page publique du site)
*/
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Send, Users, Search, Link as LinkIcon, Copy, QrCode, RotateCcw, Bell, Ban, ExternalLink, Loader2, Mail, MessageCircle, Globe } from "lucide-react";
import { apiClient } from "@/lib/api";
import { errorText, formatDateTime } from "./fieldTypes";

const STATUS = {
  sent: ["Envoyé", "bg-slate-100 text-slate-700"],
  opened: ["Ouvert", "bg-sky-100 text-sky-800"],
  answered: ["Répondu", "bg-emerald-100 text-emerald-800"],
  revoked: ["Désactivé", "bg-rose-100 text-rose-700"],
};

export default function FormSendPanel({ apiBase = "/forms", form, onChanged, publicPath = "/f" }) {
  const [recipients, setRecipients] = useState([]);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState({});
  const [channels, setChannels] = useState({ email: true, whatsapp: false });
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [invites, setInvites] = useState({ items: [], stats: {} });
  // Lien public actuel, reconstruit à partir du jeton (aucun appel au chargement).
  const initialToken = form.public_link?.token;
  const [link, setLink] = useState({
    enabled: !!form.public_link?.enabled, token: initialToken,
    url: initialToken ? `${window.location.origin}${publicPath}/${initialToken}` : null,
  });
  const [qrUrl, setQrUrl] = useState(null);
  const [statusFilter, setStatusFilter] = useState("all");

  const loadInvites = () => apiClient.get(`${apiBase}/${form.id}/invitations`).then((r) => setInvites(r.data)).catch(() => {});
  useEffect(() => {
    apiClient.get(`${apiBase}/recipients`).then((r) => setRecipients(r.data?.items || [])).catch((e) => toast.error(errorText(e)));
    loadInvites();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.id]);

  // QR code du lien public (image protégée : chargée via apiClient).
  useEffect(() => {
    let href = null;
    if (link.enabled && link.token) {
      apiClient.get(`${apiBase}/${form.id}/qr.png`, { responseType: "blob" })
        .then((r) => { href = URL.createObjectURL(r.data); setQrUrl(href); }).catch(() => setQrUrl(null));
    } else setQrUrl(null);
    return () => { if (href) URL.revokeObjectURL(href); };
  }, [link.enabled, link.token, apiBase, form.id]);

  const statusById = useMemo(() => Object.fromEntries((invites.items || []).map((i) => [i.recipient_id, i])), [invites]);
  const filtered = recipients.filter((r) => {
    const q = query.trim().toLowerCase();
    return !q || [r.name, r.company, r.email].some((v) => (v || "").toLowerCase().includes(q));
  });
  const pickedIds = Object.keys(picked).filter((k) => picked[k]);
  const allFilteredPicked = filtered.length > 0 && filtered.every((r) => picked[r.id]);

  const send = async () => {
    const ch = Object.keys(channels).filter((k) => channels[k]);
    if (!pickedIds.length) { toast.error("Choisissez au moins un destinataire."); return; }
    if (!ch.length) { toast.error("Choisissez au moins un canal."); return; }
    setSending(true);
    try {
      const r = await apiClient.post(`${apiBase}/${form.id}/invitations`, { recipient_ids: pickedIds, channels: ch, message });
      const { sent, failed } = r.data;
      if (failed) toast.warning(`${sent} envoyé(s), ${failed} échec(s) — voir le détail dans le suivi.`);
      else toast.success(`Formulaire envoyé à ${sent} destinataire(s).`);
      setPicked({}); loadInvites(); onChanged && onChanged();
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setSending(false);
    }
  };

  const setPublic = async (payload) => {
    try {
      const r = await apiClient.post(`${apiBase}/${form.id}/public-link`, payload);
      setLink(r.data); onChanged && onChanged();
      toast.success(r.data.enabled ? (payload.rotate ? "Nouveau lien créé : l'ancien ne fonctionne plus." : "Lien public activé.") : "Lien public désactivé.");
    } catch (e) { toast.error(errorText(e)); }
  };
  const copy = async (text) => { try { await navigator.clipboard.writeText(text); toast.success("Lien copié."); } catch { toast.error("Copie impossible : sélectionnez le lien à la main."); } };

  const remind = async () => {
    const ch = Object.keys(channels).filter((k) => channels[k]);
    if (!window.confirm(`Relancer les ${invites.stats?.pending || 0} destinataire(s) qui n'ont pas encore répondu ?`)) return;
    try {
      const r = await apiClient.post(`${apiBase}/${form.id}/invitations/remind`, { channels: ch.length ? ch : ["email"], message });
      toast.success(`${r.data.reminded} relance(s) envoyée(s)${r.data.failed ? `, ${r.data.failed} échec(s)` : ""}.`);
      loadInvites();
    } catch (e) { toast.error(errorText(e)); }
  };
  const revoke = async (inv) => {
    if (!window.confirm(`Désactiver le lien de ${inv.recipient_name || "ce destinataire"} ?`)) return;
    try { await apiClient.delete(`${apiBase}/${form.id}/invitations/${inv.id}`); loadInvites(); } catch (e) { toast.error(errorText(e)); }
  };

  const st = invites.stats || {};
  const shown = (invites.items || []).filter((i) => statusFilter === "all" || i.status === statusFilter);

  return (
    <div className="space-y-5" data-testid="form-send-panel">
      {form.closed_reason && <p className="rounded-lg bg-amber-50 border border-amber-200 text-amber-900 text-sm px-3 py-2">{form.closed_reason} Les destinataires ne pourront pas répondre tant qu'il n'est pas rouvert (onglet Constructeur → Réglages).</p>}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {/* 1. Envoi à des clients */}
        <section className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
          <h3 className="font-semibold inline-flex items-center gap-2"><Users className="h-4 w-4 text-primary" /> Envoyer à des clients</h3>
          <div className="relative">
            <Search className="h-4 w-4 text-slate-400 absolute left-2.5 top-2.5" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher un client (nom, société, e-mail)…" className="w-full rounded-lg border border-slate-300 pl-8 pr-3 py-2 text-sm" data-testid="send-search" />
          </div>
          <div className="flex items-center justify-between text-xs text-slate-600">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={allFilteredPicked} onChange={(e) => setPicked((p) => { const n = { ...p }; filtered.forEach((r) => { n[r.id] = e.target.checked; }); return n; })} data-testid="send-select-all" /> Tout sélectionner ({filtered.length})</label>
            <span>{pickedIds.length} sélectionné(s)</span>
          </div>
          <div className="max-h-64 overflow-y-auto divide-y divide-slate-100 rounded-lg border border-slate-100" data-testid="send-recipients">
            {filtered.map((r) => {
              const inv = statusById[r.id];
              return (
                <label key={r.id} className="flex items-center gap-2 px-2 py-1.5 text-sm hover:bg-slate-50 cursor-pointer">
                  <input type="checkbox" checked={!!picked[r.id]} onChange={(e) => setPicked({ ...picked, [r.id]: e.target.checked })} data-testid={`send-pick-${r.id}`} />
                  <span className="min-w-0 flex-1">
                    <span className="font-medium">{r.name}</span>{r.company && <span className="text-slate-500"> · {r.company}</span>}
                    <span className="block text-[11px] text-slate-400">
                      {r.can_email ? <Mail className="inline h-3 w-3" /> : <span className="line-through">e-mail</span>} {r.can_whatsapp ? <MessageCircle className="inline h-3 w-3" /> : <span className="line-through">WhatsApp</span>}
                    </span>
                  </span>
                  {inv && <span className={`text-[10px] rounded-full px-2 py-0.5 ${STATUS[inv.status][1]}`}>{STATUS[inv.status][0]}</span>}
                </label>
              );
            })}
            {filtered.length === 0 && <p className="text-xs text-slate-400 p-3">Aucun client.</p>}
          </div>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={channels.email} onChange={(e) => setChannels({ ...channels, email: e.target.checked })} data-testid="send-channel-email" /> <Mail className="h-4 w-4" /> E-mail</label>
            <label className="inline-flex items-center gap-2"><input type="checkbox" checked={channels.whatsapp} onChange={(e) => setChannels({ ...channels, whatsapp: e.target.checked })} data-testid="send-channel-whatsapp" /> <MessageCircle className="h-4 w-4" /> WhatsApp</label>
          </div>
          <textarea rows={3} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={1000} className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Message d'accompagnement (facultatif) — le lien personnel est ajouté automatiquement." />
          <button type="button" onClick={send} disabled={sending || !pickedIds.length} data-testid="send-submit"
            className="inline-flex items-center gap-2 rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium disabled:opacity-50">
            {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Envoyer à {pickedIds.length} client(s)
          </button>
          <p className="text-[11px] text-slate-500">Un client qui a déjà reçu ce formulaire garde le même lien : le renvoyer ne crée pas de doublon.</p>
        </section>

        {/* 2. Lien public */}
        <section className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
          <h3 className="font-semibold inline-flex items-center gap-2"><Globe className="h-4 w-4 text-primary" /> Lien public (non-clients)</h3>
          <p className="text-xs text-slate-600">Toute personne ayant ce lien peut répondre, sans compte. À partager par e-mail, WhatsApp, affiche (QR code), site web…</p>
          {link.enabled && link.url ? (
            <>
              <div className="flex gap-2">
                <input readOnly value={link.url} className="flex-1 rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 text-xs font-mono" data-testid="public-link-url" onFocus={(e) => e.target.select()} />
                <button type="button" onClick={() => copy(link.url)} className="rounded-lg border px-2" title="Copier"><Copy className="h-4 w-4" /></button>
                <a href={link.url} target="_blank" rel="noreferrer" className="rounded-lg border px-2 inline-flex items-center" title="Ouvrir"><ExternalLink className="h-4 w-4" /></a>
              </div>
              {qrUrl && (
                <div className="flex items-center gap-3">
                  <img src={qrUrl} alt="QR code du lien public" className="h-32 w-32 border rounded" data-testid="public-link-qr" />
                  <a href={qrUrl} download={`${form.number || "formulaire"}-qr.png`} className="text-xs text-primary inline-flex items-center gap-1"><QrCode className="h-4 w-4" /> Télécharger le QR code</a>
                </div>
              )}
              <div className="flex flex-wrap gap-2 text-xs">
                <button type="button" onClick={() => { if (window.confirm("Créer un nouveau lien ? L'ancien ne fonctionnera plus.")) setPublic({ enabled: true, rotate: true }); }} className="inline-flex items-center gap-1 rounded border px-2 py-1"><RotateCcw className="h-3 w-3" /> Nouveau lien</button>
                <button type="button" onClick={() => setPublic({ enabled: false })} className="inline-flex items-center gap-1 rounded border border-rose-300 text-rose-700 px-2 py-1" data-testid="public-link-disable"><Ban className="h-3 w-3" /> Désactiver</button>
              </div>
            </>
          ) : (
            <button type="button" onClick={() => setPublic({ enabled: true })} className="inline-flex items-center gap-2 rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium" data-testid="public-link-enable">
              <LinkIcon className="h-4 w-4" /> Activer le lien public
            </button>
          )}
        </section>
      </div>

      {/* 3. Suivi */}
      <section className="rounded-xl border border-slate-200 bg-white p-4 space-y-3" data-testid="send-tracking">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">Suivi des envois</h3>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <span><strong>{st.sent || 0}</strong> envoyé(s)</span><span><strong>{st.opened || 0}</strong> ouvert(s)</span>
            <span className="text-emerald-700"><strong>{st.answered || 0}</strong> répondu(s) ({st.response_pct || 0} %)</span>
            {st.pending > 0 && <button type="button" onClick={remind} className="inline-flex items-center gap-1 rounded-lg border border-amber-300 bg-amber-50 text-amber-900 px-2 py-1" data-testid="send-remind"><Bell className="h-3 w-3" /> Relancer les {st.pending} non-répondant(s)</button>}
          </div>
        </div>
        <div className="flex gap-1 text-xs">
          {[["all", "Tous"], ["sent", "Envoyés"], ["opened", "Ouverts"], ["answered", "Répondus"], ["revoked", "Désactivés"]].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setStatusFilter(k)} className={`rounded-full px-2.5 py-1 border ${statusFilter === k ? "bg-primary text-primary-foreground border-primary" : "bg-white border-slate-300"}`}>{l}</button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-slate-500 text-left"><tr><th className="py-1 pr-2">Destinataire</th><th className="pr-2">Statut</th><th className="pr-2">Dernier envoi</th><th className="pr-2">Canaux</th><th className="pr-2">Réponse</th><th /></tr></thead>
            <tbody>
              {shown.map((i) => {
                const last = (i.deliveries || [])[i.deliveries.length - 1];
                return (
                  <tr key={i.id} className="border-t border-slate-100" data-testid={`invite-row-${i.recipient_id}`}>
                    <td className="py-1.5 pr-2"><span className="font-medium">{i.recipient_name || i.recipient_id}</span><span className="block text-[11px] text-slate-400">{i.recipient_email}</span></td>
                    <td className="pr-2"><span className={`text-[11px] rounded-full px-2 py-0.5 ${STATUS[i.status][1]}`}>{STATUS[i.status][0]}</span></td>
                    <td className="pr-2 text-xs text-slate-500">{formatDateTime(i.last_sent_at)}{(i.deliveries || []).length > 1 ? ` (${i.deliveries.length} envois)` : ""}</td>
                    <td className="pr-2 text-xs">
                      {last && Object.entries(last.results || {}).map(([ch, res]) => (
                        <span key={ch} title={res.error || "Envoyé"} className={`mr-1 inline-flex items-center gap-0.5 ${res.ok ? "text-emerald-700" : "text-rose-600"}`}>
                          {ch === "email" ? <Mail className="h-3 w-3" /> : <MessageCircle className="h-3 w-3" />}{res.ok ? "✓" : "✗"}
                        </span>
                      ))}
                    </td>
                    <td className="pr-2 text-xs text-slate-500">{i.answered_at ? formatDateTime(i.answered_at) : i.opened_at ? `ouvert le ${formatDateTime(i.opened_at)}` : "—"}</td>
                    <td className="text-right whitespace-nowrap">
                      <button type="button" onClick={() => copy(i.url)} className="p-1 text-slate-400 hover:text-primary" title="Copier son lien personnel"><Copy className="h-3.5 w-3.5" /></button>
                      {i.status !== "revoked" && <button type="button" onClick={() => revoke(i)} className="p-1 text-slate-400 hover:text-rose-600" title="Désactiver son lien"><Ban className="h-3.5 w-3.5" /></button>}
                    </td>
                  </tr>
                );
              })}
              {shown.length === 0 && <tr><td colSpan={6} className="py-4 text-center text-xs text-slate-400">Aucun envoi.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
