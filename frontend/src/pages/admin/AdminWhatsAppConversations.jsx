import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  MessageCircle, Send, Loader2, Search, RefreshCw, ArrowLeft,
  Image as ImageIcon, Mic, FileText, MapPin, Video, Check, CheckCheck, AlertTriangle,
  Zap, Plus, Trash2, Pencil, Tag, BellRing, BellOff, BarChart3, UserPlus,
} from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList,
} from "@/components/ui/command";

/**
 * Partie 2.D + 2.E — Centre de conversations WhatsApp.
 *
 * Features :
 *  - Layout 2 colonnes desktop / pile mobile
 *  - Son + notification desktop sur nouveau message entrant (toggleable)
 *  - Quick replies CRUD via dropdown + dialog
 *  - Étiquettes de conversation (à traiter / en attente / résolu)
 *  - Lien vers page Statistiques
 */

const POLL_MS = 10000;

const LABELS = {
  todo: { text: "À traiter", bg: "bg-amber-100", fg: "text-amber-800", dot: "bg-amber-500" },
  waiting: { text: "En attente", bg: "bg-sky-100", fg: "text-sky-800", dot: "bg-sky-500" },
  resolved: { text: "Résolu", bg: "bg-emerald-100", fg: "text-emerald-800", dot: "bg-emerald-500" },
};
const LABEL_ORDER = ["todo", "waiting", "resolved"];
const LS_NOTIF = "albarka:wa:notif";

const kindIcon = (mt) => {
  switch (mt) {
    case "image": return <ImageIcon className="w-3 h-3" />;
    case "audio": return <Mic className="w-3 h-3" />;
    case "video": return <Video className="w-3 h-3" />;
    case "document": return <FileText className="w-3 h-3" />;
    case "location": return <MapPin className="w-3 h-3" />;
    default: return null;
  }
};

const preview = (m) => {
  if (!m) return "";
  if (m.last_type && m.last_type !== "text") {
    const label = { image: "Photo", audio: "Note vocale", video: "Vidéo", document: "Document", location: "Localisation" }[m.last_type] || m.last_type;
    return m.last_body ? `${label} · ${m.last_body}` : label;
  }
  return m.last_body || "";
};

const fmtDate = (iso) => {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    const today = new Date();
    if (d.toDateString() === today.toDateString()) return d.toTimeString().slice(0, 5);
    return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
  } catch { return iso.slice(0, 10); }
};

// Petit bip 440Hz 180ms via WebAudio (aucun asset à charger)
function playBeep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.type = "sine"; osc.frequency.value = 660;
    gain.gain.setValueAtTime(0.001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
    osc.start(); osc.stop(ctx.currentTime + 0.3);
    setTimeout(() => ctx.close && ctx.close(), 500);
  } catch { /* silent */ }
}

export default function AdminWhatsAppConversations() {
  const navigate = useNavigate();
  const [conversations, setConversations] = useState([]);
  const [loadingList, setLoadingList] = useState(true);
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [q, setQ] = useState("");
  const [labelFilter, setLabelFilter] = useState("all");
  const [notifEnabled, setNotifEnabled] = useState(() => localStorage.getItem(LS_NOTIF) !== "0");
  const [quickReplies, setQuickReplies] = useState([]);
  const [qrDialogOpen, setQrDialogOpen] = useState(false);
  const [qrEditing, setQrEditing] = useState(null); // {id?, label, body}
  const [qrSaving, setQrSaving] = useState(false);
  const [newConvOpen, setNewConvOpen] = useState(false);
  const [contacts, setContacts] = useState([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const scrollRef = useRef(null);
  const lastUnreadTotalRef = useRef(0);
  const firstLoadRef = useRef(true);

  const loadConversations = async ({ notify = true } = {}) => {
    try {
      const { data } = await apiClient.get("/whatsapp/conversations");
      // Détection nouveau message (comparer le total non-lus)
      const total = data.reduce((s, c) => s + (c.unread || 0), 0);
      if (notify && !firstLoadRef.current && total > lastUnreadTotalRef.current && notifEnabled) {
        // Trouver la conversation avec un unread récent
        const bumped = data.find((c) => (c.unread || 0) > 0);
        const who = bumped?.contact_name || bumped?.phone || "un contact";
        playBeep();
        try {
          if ("Notification" in window && Notification.permission === "granted") {
            new Notification("Nouveau message WhatsApp", {
              body: `${who} — ${preview(bumped) || "message reçu"}`,
              icon: "/favicon.ico",
              tag: "wa-inbox",
            });
          }
        } catch { /* silent */ }
        toast.info(`Nouveau message de ${who}`);
      }
      lastUnreadTotalRef.current = total;
      firstLoadRef.current = false;
      setConversations(data);
    } catch (err) { toast.error(extractError(err)); }
    finally { setLoadingList(false); }
  };

  const loadMessages = async (phone) => {
    if (!phone) return;
    setLoadingMsgs(true);
    try {
      const { data } = await apiClient.get(`/whatsapp/conversations/${encodeURIComponent(phone)}/messages`);
      setMessages(data);
      setTimeout(() => scrollRef.current?.scrollTo({ top: 9e9, behavior: "smooth" }), 60);
      loadConversations({ notify: false });
    } catch (err) { toast.error(extractError(err)); }
    finally { setLoadingMsgs(false); }
  };

  const loadQuickReplies = async () => {
    try {
      const { data } = await apiClient.get("/whatsapp/quick-replies");
      setQuickReplies(data);
    } catch { /* silent */ }
  };

  // Une nouvelle conversation ne peut viser qu'un destinataire déjà connu :
  // un contact (annuaire client ou cabinet) avec un numéro renseigné et le
  // canal WhatsApp activé. Un numéro tapé à la volée n'est jamais proposé —
  // s'il manque, on renvoie vers le module Contacts pour l'y créer d'abord.
  const loadContacts = async () => {
    setContactsLoading(true);
    try {
      const { data } = await apiClient.get("/contacts");
      setContacts(
        (data || []).filter(
          (c) => (c.phone || "").trim().startsWith("+") && (c.channels || []).includes("whatsapp"),
        ),
      );
    } catch (err) { toast.error(extractError(err, "Impossible de charger les contacts")); }
    finally { setContactsLoading(false); }
  };

  const openNewConversation = () => { setNewConvOpen(true); loadContacts(); };

  const startConversation = (contact) => {
    const phone = contact.phone.trim();
    setNewConvOpen(false);
    if (!conversations.some((c) => c.phone === phone)) {
      setConversations((prev) => [
        { phone, last_at: null, last_body: "", last_direction: null, last_type: null,
          contact_name: contact.full_name, count: 0, unread: 0, label: null },
        ...prev,
      ]);
    }
    setSelectedPhone(phone);
  };

  useEffect(() => { loadConversations({ notify: false }); loadQuickReplies(); }, []);
  useEffect(() => {
    const t = setInterval(() => {
      loadConversations();
      if (selectedPhone) loadMessages(selectedPhone);
    }, POLL_MS);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [selectedPhone, notifEnabled]);

  useEffect(() => { if (selectedPhone) loadMessages(selectedPhone); /* eslint-disable-next-line */ }, [selectedPhone]);

  const toggleNotif = async () => {
    const next = !notifEnabled;
    setNotifEnabled(next);
    localStorage.setItem(LS_NOTIF, next ? "1" : "0");
    if (next && "Notification" in window && Notification.permission === "default") {
      try {
        const perm = await Notification.requestPermission();
        if (perm !== "granted") toast.warning("Notifications navigateur refusées — seul le son restera actif.");
        else toast.success("Notifications activées");
      } catch { /* silent */ }
    } else if (next) {
      toast.success("Alertes activées");
    } else {
      toast.info("Alertes désactivées");
    }
  };

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    return conversations.filter((c) => {
      if (labelFilter !== "all") {
        if (labelFilter === "none" && c.label) return false;
        if (labelFilter !== "none" && c.label !== labelFilter) return false;
      }
      if (!term) return true;
      return (
        (c.phone || "").toLowerCase().includes(term) ||
        (c.contact_name || "").toLowerCase().includes(term) ||
        (c.last_body || "").toLowerCase().includes(term)
      );
    });
  }, [conversations, q, labelFilter]);

  const totalUnread = useMemo(
    () => conversations.reduce((s, c) => s + (c.unread || 0), 0),
    [conversations]
  );

  const send = async () => {
    if (!reply.trim() || !selectedPhone) return;
    setSending(true);
    try {
      const { data } = await apiClient.post(
        `/whatsapp/conversations/${encodeURIComponent(selectedPhone)}/reply`,
        { body: reply.trim() },
      );
      if (data?.result?.outside_24h_window) toast.warning("Message envoyé hors fenêtre 24h — Meta peut le refuser.");
      else if (!data?.ok) toast.error(data?.result?.error || "Envoi refusé par Meta");
      else toast.success("Réponse envoyée");
      setReply("");
      await Promise.all([loadMessages(selectedPhone), loadConversations({ notify: false })]);
    } catch (err) { toast.error(extractError(err)); }
    finally { setSending(false); }
  };

  const setLabel = async (phone, label) => {
    try {
      await apiClient.patch(`/whatsapp/conversations/${encodeURIComponent(phone)}/label`, { label });
      await loadConversations({ notify: false });
      toast.success(label ? `Étiquette "${LABELS[label].text}" appliquée` : "Étiquette retirée");
    } catch (err) { toast.error(extractError(err)); }
  };

  // --- Quick replies CRUD ---
  const openQrCreate = () => { setQrEditing({ label: "", body: "" }); setQrDialogOpen(true); };
  const openQrEdit = (qr) => { setQrEditing({ id: qr.id, label: qr.label, body: qr.body }); setQrDialogOpen(true); };
  const saveQr = async () => {
    if (!qrEditing?.label?.trim() || !qrEditing?.body?.trim()) { toast.error("Titre et message requis"); return; }
    setQrSaving(true);
    try {
      if (qrEditing.id) {
        await apiClient.patch(`/whatsapp/quick-replies/${qrEditing.id}`, { label: qrEditing.label.trim(), body: qrEditing.body.trim() });
      } else {
        await apiClient.post("/whatsapp/quick-replies", { label: qrEditing.label.trim(), body: qrEditing.body.trim(), sort_order: quickReplies.length });
      }
      await loadQuickReplies();
      setQrDialogOpen(false); setQrEditing(null);
    } catch (err) { toast.error(extractError(err)); }
    finally { setQrSaving(false); }
  };
  const deleteQr = async (id) => {
    if (!window.confirm("Supprimer cette réponse rapide ?")) return;
    try {
      await apiClient.delete(`/whatsapp/quick-replies/${id}`);
      await loadQuickReplies();
      toast.success("Réponse rapide supprimée");
    } catch (err) { toast.error(extractError(err)); }
  };

  const insertQr = (qr) => {
    setReply((prev) => prev ? `${prev}\n${qr.body}` : qr.body);
  };

  const selectedConv = conversations.find((c) => c.phone === selectedPhone);

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col" data-testid="wa-inbox-page">
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold flex items-center gap-2">
            <MessageCircle className="w-6 h-6 text-[#0F6B4A]" />
            Conversations WhatsApp
            {totalUnread > 0 && (
              <Badge className="bg-[#E5A24B] text-white" data-testid="wa-inbox-unread-total">{totalUnread}</Badge>
            )}
          </h1>
          <p className="text-sm text-muted-foreground">Messages reçus via le webhook Meta — répondez en texte libre.</p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={openNewConversation}
            className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white"
            data-testid="wa-inbox-new-conversation-btn"
          >
            <UserPlus className="w-4 h-4 mr-1" /> Nouvelle conversation
          </Button>
          <Button
            variant="outline" size="sm"
            onClick={toggleNotif}
            title={notifEnabled ? "Désactiver alertes" : "Activer alertes"}
            data-testid="wa-inbox-notif-toggle"
          >
            {notifEnabled ? <BellRing className="w-4 h-4 mr-1" /> : <BellOff className="w-4 h-4 mr-1" />}
            Alertes {notifEnabled ? "activées" : "désactivées"}
          </Button>
          <Button variant="outline" size="sm" onClick={() => navigate("/admin/whatsapp/stats")} data-testid="wa-inbox-stats-btn">
            <BarChart3 className="w-4 h-4 mr-1" /> Stats
          </Button>
          <Button variant="outline" size="sm" onClick={() => loadConversations({ notify: false })} data-testid="wa-inbox-refresh-btn">
            <RefreshCw className="w-4 h-4 mr-1" /> Rafraîchir
          </Button>
        </div>
      </div>

      <div className="flex-1 min-h-0 border border-border rounded-lg overflow-hidden bg-white grid grid-cols-1 md:grid-cols-[340px_1fr]">
        <div
          className={`border-r border-border flex flex-col min-h-0 ${selectedPhone ? "hidden md:flex" : "flex"}`}
          data-testid="wa-inbox-list-panel"
        >
          <div className="p-2 border-b border-border space-y-2">
            <div className="relative">
              <Search className="w-4 h-4 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Rechercher numéro, contact, message…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className="pl-8 h-9"
                data-testid="wa-inbox-search-input"
              />
            </div>
            {/* Filtre par étiquette */}
            <div className="flex items-center gap-1 flex-wrap">
              {[
                { v: "all", t: "Tous" },
                { v: "todo", t: "À traiter" },
                { v: "waiting", t: "En attente" },
                { v: "resolved", t: "Résolu" },
                { v: "none", t: "Sans" },
              ].map((f) => {
                const style = f.v !== "all" && f.v !== "none" ? LABELS[f.v] : null;
                const active = labelFilter === f.v;
                return (
                  <button
                    key={f.v}
                    onClick={() => setLabelFilter(f.v)}
                    className={`text-[10px] px-1.5 py-0.5 rounded border ${active ? "bg-[#0F6B4A] text-white border-[#0F6B4A]" : "bg-white border-slate-200 hover:bg-slate-50"}`}
                    data-testid={`wa-inbox-label-filter-${f.v}`}
                  >
                    {style && <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1 ${style.dot}`} />}
                    {f.t}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto" data-testid="wa-inbox-list">
            {loadingList && (
              <div className="p-6 text-center text-sm text-muted-foreground">
                <Loader2 className="w-4 h-4 animate-spin inline mr-2" />Chargement…
              </div>
            )}
            {!loadingList && filtered.length === 0 && (
              <div className="p-6 text-center text-sm text-muted-foreground">
                Aucune conversation.
                {conversations.length === 0 && (
                  <div className="mt-2 text-xs">En attente du premier message entrant via le webhook Meta.</div>
                )}
              </div>
            )}
            {filtered.map((c) => {
              const isActive = c.phone === selectedPhone;
              const lbl = c.label ? LABELS[c.label] : null;
              return (
                <button
                  key={c.phone}
                  onClick={() => setSelectedPhone(c.phone)}
                  className={`w-full text-left px-3 py-2.5 border-b border-slate-100 hover:bg-slate-50 transition ${isActive ? "bg-emerald-50" : ""}`}
                  data-testid={`wa-inbox-conv-${c.phone}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-sm truncate flex items-center gap-1.5">
                      {lbl && <span className={`inline-block w-2 h-2 rounded-full ${lbl.dot}`} title={lbl.text} />}
                      {c.contact_name || c.phone}
                    </div>
                    <div className="text-[10px] text-muted-foreground shrink-0">{fmtDate(c.last_at)}</div>
                  </div>
                  <div className="flex items-center justify-between gap-2 mt-0.5">
                    <div className="text-xs text-muted-foreground truncate flex items-center gap-1">
                      {c.last_direction === "outbound" && <CheckCheck className="w-3 h-3 shrink-0" />}
                      {kindIcon(c.last_type)}
                      <span className="truncate">{preview(c)}</span>
                    </div>
                    {c.unread > 0 && (
                      <Badge className="bg-[#E5A24B] text-white h-5 min-w-5 px-1.5 text-[10px]">{c.unread}</Badge>
                    )}
                  </div>
                  {c.contact_name && <div className="text-[10px] text-muted-foreground mt-0.5">{c.phone}</div>}
                </button>
              );
            })}
          </div>
        </div>

        {/* Fil */}
        <div
          className={`flex flex-col min-h-0 ${selectedPhone ? "flex" : "hidden md:flex"}`}
          data-testid="wa-inbox-thread-panel"
        >
          {!selectedPhone && (
            <div className="flex-1 flex items-center justify-center text-center p-8 text-muted-foreground">
              <div>
                <MessageCircle className="w-12 h-12 mx-auto mb-3 opacity-40" />
                <div className="text-sm">Sélectionnez une conversation pour afficher les messages.</div>
              </div>
            </div>
          )}

          {selectedPhone && (
            <>
              <div className="p-3 border-b border-border bg-[#0F6B4A] text-white flex items-center gap-2">
                <button
                  onClick={() => setSelectedPhone(null)}
                  className="md:hidden hover:bg-white/10 p-1 rounded"
                  data-testid="wa-inbox-back-btn"
                ><ArrowLeft className="w-4 h-4" /></button>
                <div className="min-w-0 flex-1">
                  <div className="font-semibold text-sm truncate">{selectedConv?.contact_name || selectedPhone}</div>
                  <div className="text-[11px] opacity-80">{selectedPhone}</div>
                </div>
                {/* Étiquette */}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size="sm" variant="secondary" className="h-7 px-2 text-xs" data-testid="wa-inbox-label-btn">
                      <Tag className="w-3 h-3 mr-1" />
                      {selectedConv?.label ? LABELS[selectedConv.label].text : "Étiquette"}
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-44">
                    <DropdownMenuLabel className="text-xs">Étiquette</DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    {LABEL_ORDER.map((k) => (
                      <DropdownMenuItem
                        key={k}
                        onClick={() => setLabel(selectedPhone, k)}
                        data-testid={`wa-inbox-set-label-${k}`}
                      >
                        <span className={`inline-block w-2 h-2 rounded-full mr-2 ${LABELS[k].dot}`} />
                        {LABELS[k].text}
                        {selectedConv?.label === k && <Check className="w-3 h-3 ml-auto" />}
                      </DropdownMenuItem>
                    ))}
                    {selectedConv?.label && (
                      <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                          onClick={() => setLabel(selectedPhone, null)}
                          className="text-red-600"
                          data-testid="wa-inbox-set-label-none"
                        >
                          Retirer l'étiquette
                        </DropdownMenuItem>
                      </>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
                <a
                  href={`https://wa.me/${selectedPhone.replace(/[^0-9]/g, "")}`}
                  target="_blank" rel="noopener noreferrer"
                  className="text-[11px] underline opacity-80 hover:opacity-100 hidden sm:inline"
                  data-testid="wa-inbox-external-link"
                >Ouvrir dans WhatsApp</a>
              </div>

              <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-2 bg-slate-50" data-testid="wa-inbox-messages">
                {loadingMsgs && (
                  <div className="text-center text-sm text-muted-foreground py-8">
                    <Loader2 className="w-4 h-4 animate-spin inline mr-2" />Chargement…
                  </div>
                )}
                {!loadingMsgs && messages.length === 0 && (
                  <div className="text-center text-sm text-muted-foreground py-8">Aucun message dans cette conversation.</div>
                )}
                {messages.map((m) => {
                  const outbound = m.direction === "outbound";
                  return (
                    <div key={m.id} className={`flex ${outbound ? "justify-end" : "justify-start"}`} data-testid={`wa-msg-${m.id}`}>
                      <div className={`max-w-[85%] rounded-lg p-2 shadow-sm text-sm ${outbound ? "bg-[#0F6B4A] text-white" : "bg-white border border-border"}`}>
                        <div className={`text-[10px] mb-0.5 flex items-center gap-1 ${outbound ? "text-white/70" : "text-muted-foreground"}`}>
                          {kindIcon(m.message_type)}
                          <span>{outbound ? (m.sent_by_name || "Cabinet") : (m.contact_name || m.profile_name || m.phone)}</span>
                          <span>·</span>
                          <span>{m.created_at?.slice(11, 16)}</span>
                          {outbound && m.wa_error && (
                            <span title={m.wa_error} className="ml-1"><AlertTriangle className="w-3 h-3 text-amber-300" /></span>
                          )}
                          {outbound && !m.wa_error && <Check className="w-3 h-3 ml-1" />}
                        </div>
                        {m.message_type === "location" && <div className="italic opacity-80">📍 Localisation partagée</div>}
                        {["image", "video", "audio", "document"].includes(m.message_type) && !m.body && !m.voice_note_transcript && (
                          <div className="italic opacity-80">
                            [{m.message_type}{m.media_mime ? ` · ${m.media_mime}` : ""}]
                          </div>
                        )}
                        {m.voice_note_transcript && (
                          <div className={`italic ${outbound ? "text-white/90" : "text-slate-600"} mb-1`}>🎙️ {m.voice_note_transcript}</div>
                        )}
                        {m.body && <div className="whitespace-pre-wrap break-words">{m.body}</div>}
                        {outbound && m.outside_24h_window && (
                          <div className="text-[10px] mt-1 text-amber-300">Hors fenêtre 24h</div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="p-2 border-t border-border bg-white flex gap-2 items-stretch">
                {/* Dropdown quick replies */}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" size="sm" className="self-stretch px-2" title="Réponses rapides" data-testid="wa-inbox-qr-menu-btn">
                      <Zap className="w-4 h-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="w-72 max-h-80 overflow-y-auto">
                    <DropdownMenuLabel className="text-xs flex items-center justify-between">
                      Réponses rapides
                      <Button size="sm" variant="ghost" className="h-6 px-1" onClick={openQrCreate} data-testid="wa-inbox-qr-new-btn">
                        <Plus className="w-3 h-3" />
                      </Button>
                    </DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    {quickReplies.length === 0 && (
                      <div className="p-3 text-xs text-muted-foreground">
                        Aucune réponse rapide. Cliquez sur + pour en ajouter.
                      </div>
                    )}
                    {quickReplies.map((qr) => (
                      <div key={qr.id} className="px-2 py-1.5 hover:bg-slate-50 group" data-testid={`wa-inbox-qr-item-${qr.id}`}>
                        <button
                          onClick={() => insertQr(qr)}
                          className="w-full text-left"
                          data-testid={`wa-inbox-qr-insert-${qr.id}`}
                        >
                          <div className="text-xs font-medium truncate">{qr.label}</div>
                          <div className="text-[11px] text-muted-foreground line-clamp-2">{qr.body}</div>
                        </button>
                        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition mt-1">
                          <button
                            onClick={(e) => { e.stopPropagation(); openQrEdit(qr); }}
                            className="text-[10px] text-slate-500 hover:text-slate-800 inline-flex items-center gap-0.5"
                            data-testid={`wa-inbox-qr-edit-${qr.id}`}
                          ><Pencil className="w-3 h-3" /> Modifier</button>
                          <button
                            onClick={(e) => { e.stopPropagation(); deleteQr(qr.id); }}
                            className="text-[10px] text-red-500 hover:text-red-700 inline-flex items-center gap-0.5"
                            data-testid={`wa-inbox-qr-delete-${qr.id}`}
                          ><Trash2 className="w-3 h-3" /> Supprimer</button>
                        </div>
                      </div>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
                <Textarea
                  rows={2}
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder="Répondre… (Entrée pour envoyer, Maj+Entrée pour nouvelle ligne)"
                  className="resize-none text-sm min-h-[42px] flex-1"
                  data-testid="wa-inbox-reply-input"
                />
                <Button
                  onClick={send}
                  disabled={!reply.trim() || sending}
                  className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white self-stretch px-3"
                  data-testid="wa-inbox-send-btn"
                >
                  {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </Button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Dialog Nouvelle conversation — un contact existant uniquement */}
      <Dialog open={newConvOpen} onOpenChange={setNewConvOpen}>
        <DialogContent data-testid="wa-inbox-new-conv-dialog">
          <DialogHeader>
            <DialogTitle>Nouvelle conversation</DialogTitle>
            <DialogDescription className="text-xs">
              Choisissez un contact déjà enregistré (client ou cabinet) avec WhatsApp activé.
              Un nouveau contact se crée d'abord dans le module Contacts.
            </DialogDescription>
          </DialogHeader>
          <Command>
            <CommandInput placeholder="Rechercher un contact…" data-testid="wa-inbox-new-conv-search" />
            <CommandList>
              {contactsLoading ? (
                <div className="p-4 text-center text-sm text-muted-foreground">
                  <Loader2 className="w-4 h-4 animate-spin inline mr-2" />Chargement…
                </div>
              ) : (
                <>
                  <CommandEmpty>
                    <div className="p-2 text-center text-sm text-muted-foreground">
                      Aucun contact avec WhatsApp activé.
                      <Button
                        variant="link" size="sm" className="block mx-auto"
                        onClick={() => { setNewConvOpen(false); navigate("/admin/contacts"); }}
                        data-testid="wa-inbox-new-conv-goto-contacts"
                      >
                        Créer un contact →
                      </Button>
                    </div>
                  </CommandEmpty>
                  <CommandGroup>
                    {contacts.map((c) => (
                      <CommandItem
                        key={c.id}
                        value={`${c.full_name} ${c.organization || ""} ${c.phone}`}
                        onSelect={() => startConversation(c)}
                        data-testid={`wa-inbox-new-conv-option-${c.id}`}
                      >
                        <div className="flex flex-col">
                          <span className="font-medium flex items-center gap-1.5">
                            {c.full_name}
                            <Badge variant="secondary" className="text-[9px] uppercase">
                              {c.scope === "client" ? "Client" : "Cabinet"}
                            </Badge>
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {c.phone}{c.organization ? ` — ${c.organization}` : ""}
                          </span>
                        </div>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </DialogContent>
      </Dialog>

      {/* Dialog Quick Reply (create/edit) */}
      <Dialog open={qrDialogOpen} onOpenChange={setQrDialogOpen}>
        <DialogContent data-testid="wa-inbox-qr-dialog">
          <DialogHeader>
            <DialogTitle>{qrEditing?.id ? "Modifier la réponse rapide" : "Nouvelle réponse rapide"}</DialogTitle>
            <DialogDescription className="text-xs">
              Ces snippets seront disponibles dans le menu Réponses rapides pour toute l'équipe.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium">Titre court</label>
              <Input
                value={qrEditing?.label || ""}
                onChange={(e) => setQrEditing((p) => ({ ...(p || {}), label: e.target.value }))}
                placeholder="Ex. Accusé de réception"
                data-testid="wa-inbox-qr-label-input"
              />
            </div>
            <div>
              <label className="text-xs font-medium">Message</label>
              <Textarea
                rows={4}
                value={qrEditing?.body || ""}
                onChange={(e) => setQrEditing((p) => ({ ...(p || {}), body: e.target.value }))}
                placeholder="Bonjour, nous avons bien reçu votre demande…"
                data-testid="wa-inbox-qr-body-input"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setQrDialogOpen(false)} data-testid="wa-inbox-qr-cancel-btn">Annuler</Button>
            <Button onClick={saveQr} disabled={qrSaving} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="wa-inbox-qr-save-btn">
              {qrSaving ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : null}
              Enregistrer
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
