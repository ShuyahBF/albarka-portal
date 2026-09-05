import React, { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  MessageCircle, Send, Loader2, Search, RefreshCw, ArrowLeft,
  Image as ImageIcon, Mic, FileText, MapPin, Video, Check, CheckCheck, AlertTriangle,
} from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";

/**
 * Partie 2.D — Centre de conversations WhatsApp.
 *
 * Layout :
 *  - Desktop : 2 colonnes (liste conversations à gauche, fil à droite)
 *  - Mobile  : pile — on affiche la liste OU la conversation (bouton retour)
 *
 * Endpoints backend :
 *  GET  /whatsapp/conversations                         → liste groupée par numéro
 *  GET  /whatsapp/conversations/{phone}/messages        → messages du fil (marque lus)
 *  POST /whatsapp/conversations/{phone}/reply {body}    → envoi réponse texte
 */

const POLL_MS = 10000;

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

export default function AdminWhatsAppConversations() {
  const [conversations, setConversations] = useState([]);
  const [loadingList, setLoadingList] = useState(true);
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [q, setQ] = useState("");
  const scrollRef = useRef(null);

  const loadConversations = async () => {
    try {
      const { data } = await apiClient.get("/whatsapp/conversations");
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
      // Rafraîchir la liste pour reset le compteur de non-lus
      loadConversations();
    } catch (err) { toast.error(extractError(err)); }
    finally { setLoadingMsgs(false); }
  };

  useEffect(() => { loadConversations(); }, []);
  useEffect(() => {
    const t = setInterval(() => {
      loadConversations();
      if (selectedPhone) loadMessages(selectedPhone);
    }, POLL_MS);
    return () => clearInterval(t);
  }, [selectedPhone]);

  useEffect(() => { if (selectedPhone) loadMessages(selectedPhone); }, [selectedPhone]);

  const filtered = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return conversations;
    return conversations.filter((c) =>
      (c.phone || "").toLowerCase().includes(term) ||
      (c.contact_name || "").toLowerCase().includes(term) ||
      (c.last_body || "").toLowerCase().includes(term)
    );
  }, [conversations, q]);

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
      if (data?.result?.outside_24h_window) {
        toast.warning("Message envoyé hors fenêtre 24h — Meta peut le refuser.");
      } else if (!data?.ok) {
        toast.error(data?.result?.error || "Envoi refusé par Meta");
      } else {
        toast.success("Réponse envoyée");
      }
      setReply("");
      await Promise.all([loadMessages(selectedPhone), loadConversations()]);
    } catch (err) { toast.error(extractError(err)); }
    finally { setSending(false); }
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
        <Button variant="outline" size="sm" onClick={loadConversations} data-testid="wa-inbox-refresh-btn">
          <RefreshCw className="w-4 h-4 mr-1" /> Rafraîchir
        </Button>
      </div>

      <div className="flex-1 min-h-0 border border-border rounded-lg overflow-hidden bg-white grid grid-cols-1 md:grid-cols-[340px_1fr]">
        {/* Colonne liste — masquée sur mobile quand une conv est ouverte */}
        <div
          className={`border-r border-border flex flex-col min-h-0 ${selectedPhone ? "hidden md:flex" : "flex"}`}
          data-testid="wa-inbox-list-panel"
        >
          <div className="p-2 border-b border-border">
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
                  <div className="mt-2 text-xs">
                    En attente du premier message entrant via le webhook Meta.
                  </div>
                )}
              </div>
            )}
            {filtered.map((c) => {
              const isActive = c.phone === selectedPhone;
              return (
                <button
                  key={c.phone}
                  onClick={() => setSelectedPhone(c.phone)}
                  className={`w-full text-left px-3 py-2.5 border-b border-slate-100 hover:bg-slate-50 transition ${isActive ? "bg-emerald-50" : ""}`}
                  data-testid={`wa-inbox-conv-${c.phone}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium text-sm truncate">
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
                  {c.contact_name && (
                    <div className="text-[10px] text-muted-foreground mt-0.5">{c.phone}</div>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* Colonne fil de conversation */}
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
                >
                  <ArrowLeft className="w-4 h-4" />
                </button>
                <div className="min-w-0 flex-1">
                  <div className="font-semibold text-sm truncate">
                    {selectedConv?.contact_name || selectedPhone}
                  </div>
                  <div className="text-[11px] opacity-80">{selectedPhone}</div>
                </div>
                <a
                  href={`https://wa.me/${selectedPhone.replace(/[^0-9]/g, "")}`}
                  target="_blank" rel="noopener noreferrer"
                  className="text-[11px] underline opacity-80 hover:opacity-100"
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
                  <div className="text-center text-sm text-muted-foreground py-8">
                    Aucun message dans cette conversation.
                  </div>
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
                        {m.message_type === "location" && (
                          <div className="italic opacity-80">📍 Localisation partagée</div>
                        )}
                        {["image", "video", "audio", "document"].includes(m.message_type) && !m.body && !m.voice_note_transcript && (
                          <div className="italic opacity-80">
                            [{m.message_type}{m.media_mime ? ` · ${m.media_mime}` : ""}]
                          </div>
                        )}
                        {m.voice_note_transcript && (
                          <div className={`italic ${outbound ? "text-white/90" : "text-slate-600"} mb-1`}>
                            🎙️ {m.voice_note_transcript}
                          </div>
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

              <div className="p-2 border-t border-border bg-white flex gap-2">
                <Textarea
                  rows={2}
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder="Répondre… (Entrée pour envoyer, Maj+Entrée pour nouvelle ligne)"
                  className="resize-none text-sm min-h-[42px]"
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
    </div>
  );
}
