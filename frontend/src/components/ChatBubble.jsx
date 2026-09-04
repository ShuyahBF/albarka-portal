import React, { useEffect, useMemo, useRef, useState } from "react";
import { MessageSquare, X, Send, Users } from "lucide-react";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/AuthContext";

/**
 * ChatBubble — widget flottant (Point 1).
 *
 * Rendu globalement dans PortalLayout : visible sur toutes les pages
 * admin ET client. Un badge indique le nombre de messages non lus
 * (compte des messages où `author_is_client !== isClient` postérieurs
 * au dernier `seen_at` stocké en `localStorage`).
 */
const LS_KEY = "albarka:chat:seen_at";

export default function ChatBubble() {
  const { user, isClient } = useAuth();
  const [open, setOpen] = useState(false);
  const [threads, setThreads] = useState([]);
  const [clients, setClients] = useState([]);
  const [activeThread, setActiveThread] = useState(null);
  const [messages, setMessages] = useState([]);
  const [body, setBody] = useState("");
  const [newTenantId, setNewTenantId] = useState("");
  const [seenAt, setSeenAt] = useState(() => localStorage.getItem(LS_KEY) || "1970-01-01");
  const scrollRef = useRef(null);

  const clientName = (threadId) => {
    if (!threadId) return "";
    const id = threadId.startsWith("client:") ? threadId.slice(7) : threadId;
    const c = clients.find((x) => x.id === id);
    return c ? `${c.full_name}${c.company ? ` — ${c.company}` : ""}` : id;
  };

  const loadThreads = async () => {
    if (!user) return;
    try {
      if (isClient) {
        setThreads([{ thread_id: `client:${user.id}`, last_at: null, last_body: "", count: 0 }]);
        if (!activeThread) setActiveThread(`client:${user.id}`);
      } else {
        const [{ data: t }, { data: c }] = await Promise.all([
          apiClient.get("/chat/threads"),
          apiClient.get("/clients"),
        ]);
        setThreads(t); setClients(c);
      }
    } catch (err) {
      // silent — le widget ne doit pas polluer l'UI si l'API tombe
    }
  };

  const loadMessages = async () => {
    if (!activeThread) return;
    try {
      const { data } = await apiClient.get("/chat/messages", { params: { thread_id: activeThread } });
      setMessages(data);
      setTimeout(() => scrollRef.current?.scrollTo({ top: 999999, behavior: "smooth" }), 50);
    } catch (err) {
      // idem — silencieux
    }
  };

  // Chargement initial + polling léger (30s) tant que le widget est monté.
  useEffect(() => {
    loadThreads();
    const t = setInterval(loadThreads, 30000);
    return () => clearInterval(t);
  }, [user?.id]);

  useEffect(() => { loadMessages(); }, [activeThread]);

  // Compte des messages non lus (staff : tous fils confondus ; client : son fil seul).
  const unreadCount = useMemo(() => {
    // Compte à partir des `last_at` des threads > seenAt et l'auteur n'est pas moi.
    if (isClient) {
      return messages.filter((m) => m.author_is_client === false && (m.created_at || "") > seenAt).length;
    }
    return threads.reduce((n, t) => {
      if ((t.last_at || "") > seenAt) return n + 1; // 1 fil non lu = 1
      return n;
    }, 0);
  }, [threads, messages, seenAt, isClient]);

  const markSeen = () => {
    const now = new Date().toISOString();
    localStorage.setItem(LS_KEY, now);
    setSeenAt(now);
  };

  const openBubble = () => { setOpen(true); markSeen(); };

  const send = async () => {
    if (!body.trim() || !activeThread) return;
    try {
      await apiClient.post("/chat/messages", { thread_id: activeThread, body: body.trim() });
      setBody("");
      await Promise.all([loadMessages(), loadThreads()]);
      markSeen();
    } catch (err) { toast.error(extractError(err)); }
  };

  const startThread = () => {
    if (!newTenantId) return;
    const tid = `client:${newTenantId}`;
    setActiveThread(tid);
    setThreads((prev) => prev.some((t) => t.thread_id === tid) ? prev : [{ thread_id: tid, last_at: null, last_body: "(nouveau fil)", count: 0 }, ...prev]);
    setNewTenantId("");
  };

  if (!user) return null;

  return (
    <>
      {/* Bouton bulle */}
      {!open && (
        <button
          onClick={openBubble}
          className="fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full bg-[#0F6B4A] text-white shadow-lg hover:bg-[#0A4E36] transition-all hover:scale-105 flex items-center justify-center"
          data-testid="chat-bubble-toggle"
          title="Chat interne"
        >
          <MessageSquare className="w-6 h-6" />
          {unreadCount > 0 && (
            <span
              className="absolute -top-1 -right-1 bg-[#E5A24B] text-white text-xs font-bold rounded-full h-6 w-6 flex items-center justify-center border-2 border-white"
              data-testid="chat-unread-badge"
            >
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>
      )}

      {/* Panneau flottant */}
      {open && (
        <div
          className="fixed bottom-6 right-6 z-50 w-[380px] h-[540px] max-h-[85vh] bg-white rounded-xl shadow-2xl border border-border flex flex-col"
          data-testid="chat-bubble-panel"
        >
          {/* Header */}
          <div className="p-3 border-b border-border flex items-center justify-between bg-[#0F6B4A] text-white rounded-t-xl">
            <div className="flex items-center gap-2 min-w-0">
              <MessageSquare className="w-4 h-4 shrink-0" />
              <span className="text-sm font-medium truncate">
                {activeThread ? (isClient ? "Mon cabinet" : clientName(activeThread)) : "Chat interne"}
              </span>
            </div>
            <button onClick={() => setOpen(false)} className="hover:bg-white/10 p-1 rounded" data-testid="chat-bubble-close">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Sélecteur fil pour staff */}
          {!isClient && threads.length > 0 && (
            <div className="p-2 border-b border-border flex items-center gap-2 bg-slate-50">
              <Users className="w-3 h-3 text-slate-500 shrink-0" />
              <select
                className="flex-1 h-7 text-xs bg-white rounded border border-input px-1"
                value={activeThread || ""}
                onChange={(e) => setActiveThread(e.target.value)}
                data-testid="chat-bubble-thread-select"
              >
                <option value="">— Choisir un fil —</option>
                {threads.map((t) => (
                  <option key={t.thread_id} value={t.thread_id}>{clientName(t.thread_id)}</option>
                ))}
              </select>
            </div>
          )}
          {!isClient && (
            <div className="p-2 border-b border-border flex gap-1 items-center">
              <select
                className="flex-1 h-7 text-xs bg-white rounded border border-input px-1"
                value={newTenantId}
                onChange={(e) => setNewTenantId(e.target.value)}
                data-testid="chat-bubble-new-tenant-select"
              >
                <option value="">— Nouveau fil client —</option>
                {clients.map((c) => (<option key={c.id} value={c.id}>{c.full_name}</option>))}
              </select>
              <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={startThread} data-testid="chat-bubble-start-thread-btn">Ouvrir</Button>
            </div>
          )}

          {/* Messages */}
          <div ref={scrollRef} className="flex-1 p-3 overflow-y-auto space-y-2 bg-slate-50" data-testid="chat-bubble-messages">
            {!activeThread && <div className="text-xs text-muted-foreground text-center py-10">Sélectionnez un fil pour commencer.</div>}
            {activeThread && messages.length === 0 && (
              <div className="text-xs text-muted-foreground text-center py-10">Aucun message. Écrivez le premier.</div>
            )}
            {messages.map((m) => {
              const mine = (m.author_is_client && isClient) || (!m.author_is_client && !isClient);
              return (
                <div key={m.id} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[80%] p-2 rounded-lg text-sm ${mine ? "bg-[#0F6B4A] text-white" : "bg-white border border-border"}`}>
                    <div className={`text-[10px] mb-0.5 ${mine ? "text-white/70" : "text-muted-foreground"}`}>
                      {m.author_name} · {m.created_at?.slice(11, 16)}
                    </div>
                    <div className="whitespace-pre-wrap">{m.body}</div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Composer */}
          {activeThread && (
            <div className="p-2 border-t border-border flex gap-2 bg-white rounded-b-xl">
              <Textarea
                rows={2}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
                }}
                placeholder="Écrire un message… (Entrée pour envoyer)"
                className="text-sm resize-none min-h-[40px]"
                data-testid="chat-bubble-body-input"
              />
              <Button
                onClick={send}
                disabled={!body.trim()}
                className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white self-stretch px-3"
                data-testid="chat-bubble-send-btn"
              >
                <Send className="w-4 h-4" />
              </Button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
