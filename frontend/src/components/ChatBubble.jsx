import React, { useEffect, useMemo, useRef, useState } from "react";
import { MessageSquare, X, Send, Users, Mic, Square, Search, Camera, Loader2, Image as ImageIcon } from "lucide-react";
import { toast } from "sonner";
import { apiClient, extractError, API } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/AuthContext";

const LS_KEY = "albarka:chat:seen_at";

/**
 * ChatBubble — bulle flottante globale (admin + client).
 *
 * Partie 1 :
 *  - A. Note vocale → texte (bouton micro, MediaRecorder, POST /chat/transcribe)
 *  - B. Recherche plein texte (Ctrl/Cmd+K → GET /chat/search)
 *  - C. Plein écran redimensionnable sur mobile (<768px)
 *  - D. Photo (bouton camera, POST /chat/messages/photo)
 * Polling ramené de 30s à 10s.
 */
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
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [uploadingPhoto, setUploadingPhoto] = useState(false);
  const scrollRef = useRef(null);
  const mediaRef = useRef(null);
  const chunksRef = useRef([]);
  const fileInputRef = useRef(null);
  const messageRefs = useRef({});

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
    } catch (err) { /* silent */ }
  };

  const loadMessages = async () => {
    if (!activeThread) return;
    try {
      const { data } = await apiClient.get("/chat/messages", { params: { thread_id: activeThread } });
      setMessages(data);
      setTimeout(() => scrollRef.current?.scrollTo({ top: 999999, behavior: "smooth" }), 50);
    } catch (err) { /* silent */ }
  };

  useEffect(() => {
    loadThreads();
    const t = setInterval(loadThreads, 10000);
    return () => clearInterval(t);
  }, [user?.id]);

  useEffect(() => { loadMessages(); }, [activeThread]);

  // Ctrl/Cmd+K → ouvre recherche
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (open) { setSearchOpen((v) => !v); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Recherche avec debounce 250ms
  useEffect(() => {
    if (!searchOpen || !searchTerm.trim()) { setSearchResults([]); return; }
    const t = setTimeout(async () => {
      try {
        const params = { q: searchTerm.trim() };
        if (!isClient && activeThread) params.thread_id = activeThread;
        const { data } = await apiClient.get("/chat/search", { params });
        setSearchResults(data);
      } catch (err) { /* silent */ }
    }, 250);
    return () => clearTimeout(t);
  }, [searchTerm, searchOpen, activeThread, isClient]);

  const unreadCount = useMemo(() => {
    if (isClient) {
      return messages.filter((m) => m.author_is_client === false && (m.created_at || "") > seenAt).length;
    }
    return threads.reduce((n, t) => ((t.last_at || "") > seenAt ? n + 1 : n), 0);
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

  // --- Partie 1.A — Note vocale ---
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const options = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? { mimeType: "audio/webm;codecs=opus" } : {};
      const rec = new MediaRecorder(stream, options);
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data.size > 0 && chunksRef.current.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
        if (blob.size === 0) return;
        setTranscribing(true);
        try {
          const fd = new FormData();
          fd.append("audio", blob, "note.webm");
          fd.append("language", "fr");
          const res = await apiClient.post("/chat/transcribe", fd, { headers: { "Content-Type": "multipart/form-data" } });
          if (res.data?.text) setBody((prev) => prev ? `${prev} ${res.data.text}` : res.data.text);
        } catch (err) { toast.error(extractError(err, "Transcription échouée")); }
        finally { setTranscribing(false); }
      };
      mediaRef.current = rec;
      rec.start();
      setRecording(true);
    } catch (err) { toast.error("Accès micro refusé"); }
  };
  const stopRecording = () => {
    mediaRef.current?.stop();
    setRecording(false);
  };

  // --- Partie 1.D — Photo ---
  const pickPhoto = () => fileInputRef.current?.click();
  const uploadPhoto = async (file) => {
    if (!file || !activeThread) return;
    if (file.size > 10 * 1024 * 1024) { toast.error("Photo trop volumineuse (max 10 Mo)"); return; }
    setUploadingPhoto(true);
    try {
      const fd = new FormData();
      fd.append("thread_id", activeThread);
      fd.append("caption", body);
      fd.append("photo", file);
      await apiClient.post("/chat/messages/photo", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setBody("");
      await loadMessages();
    } catch (err) { toast.error(extractError(err)); }
    finally { setUploadingPhoto(false); if (fileInputRef.current) fileInputRef.current.value = ""; }
  };

  if (!user) return null;

  // Panel — plein écran mobile, bulle fixe desktop (Partie 1.C)
  const panelClasses = "fixed z-50 bg-white shadow-2xl border border-border flex flex-col md:bottom-6 md:right-6 md:w-[400px] md:h-[560px] md:max-h-[85vh] md:rounded-xl inset-0 md:inset-auto";

  return (
    <>
      {!open && (
        <button
          onClick={openBubble}
          className="fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full bg-[#0F6B4A] text-white shadow-lg hover:bg-[#0A4E36] transition-all hover:scale-105 flex items-center justify-center"
          data-testid="chat-bubble-toggle"
        >
          <MessageSquare className="w-6 h-6" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 bg-[#E5A24B] text-white text-xs font-bold rounded-full h-6 w-6 flex items-center justify-center border-2 border-white" data-testid="chat-unread-badge">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          )}
        </button>
      )}

      {open && (
        <div className={panelClasses} data-testid="chat-bubble-panel">
          <div className="p-3 border-b border-border flex items-center justify-between bg-[#0F6B4A] text-white md:rounded-t-xl">
            <div className="flex items-center gap-2 min-w-0">
              <MessageSquare className="w-4 h-4 shrink-0" />
              <span className="text-sm font-medium truncate">
                {activeThread ? (isClient ? "Mon cabinet" : clientName(activeThread)) : "Chat interne"}
              </span>
            </div>
            <div className="flex items-center gap-1">
              <button onClick={() => setSearchOpen((v) => !v)} className="hover:bg-white/10 p-1 rounded" data-testid="chat-search-toggle" title="Rechercher (Ctrl/Cmd+K)">
                <Search className="w-4 h-4" />
              </button>
              <button onClick={() => setOpen(false)} className="hover:bg-white/10 p-1 rounded" data-testid="chat-bubble-close">
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {searchOpen && (
            <div className="p-2 border-b border-border bg-slate-50 space-y-2" data-testid="chat-search-panel">
              <Input autoFocus placeholder="Rechercher dans les messages…" value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} className="h-8 text-sm" data-testid="chat-search-input" />
              {searchResults.length > 0 && (
                <div className="max-h-40 overflow-y-auto text-xs space-y-1">
                  {searchResults.map((m) => (
                    <button
                      key={m.id}
                      onClick={() => {
                        if (m.thread_id !== activeThread) setActiveThread(m.thread_id);
                        setSearchOpen(false); setSearchTerm("");
                        setTimeout(() => {
                          const el = messageRefs.current[m.id];
                          if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" });
                            el.classList.add("ring-2", "ring-[#E5A24B]");
                            setTimeout(() => el.classList.remove("ring-2", "ring-[#E5A24B]"), 2500); }
                        }, 200);
                      }}
                      className="w-full text-left p-2 bg-white rounded hover:bg-slate-100 border border-slate-200"
                      data-testid={`chat-search-result-${m.id}`}
                    >
                      <div className="font-medium truncate">{m.author_name}</div>
                      <div className="text-muted-foreground truncate">{m.body}</div>
                    </button>
                  ))}
                </div>
              )}
              {searchTerm && searchResults.length === 0 && <div className="text-xs text-muted-foreground text-center py-2">Aucun résultat.</div>}
            </div>
          )}

          {!isClient && threads.length > 0 && (
            <div className="p-2 border-b border-border flex items-center gap-2 bg-slate-50">
              <Users className="w-3 h-3 text-slate-500 shrink-0" />
              <select className="flex-1 h-7 text-xs bg-white rounded border border-input px-1" value={activeThread || ""} onChange={(e) => setActiveThread(e.target.value)} data-testid="chat-bubble-thread-select">
                <option value="">— Choisir un fil —</option>
                {threads.map((t) => (<option key={t.thread_id} value={t.thread_id}>{clientName(t.thread_id)}</option>))}
              </select>
            </div>
          )}
          {!isClient && (
            <div className="p-2 border-b border-border flex gap-1 items-center">
              <select className="flex-1 h-7 text-xs bg-white rounded border border-input px-1" value={newTenantId} onChange={(e) => setNewTenantId(e.target.value)} data-testid="chat-bubble-new-tenant-select">
                <option value="">— Nouveau fil client —</option>
                {clients.map((c) => (<option key={c.id} value={c.id}>{c.full_name}</option>))}
              </select>
              <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={startThread} data-testid="chat-bubble-start-thread-btn">Ouvrir</Button>
            </div>
          )}

          <div ref={scrollRef} className="flex-1 p-3 overflow-y-auto space-y-2 bg-slate-50" data-testid="chat-bubble-messages">
            {!activeThread && <div className="text-xs text-muted-foreground text-center py-10">Sélectionnez un fil pour commencer.</div>}
            {activeThread && messages.length === 0 && <div className="text-xs text-muted-foreground text-center py-10">Aucun message. Écrivez le premier.</div>}
            {messages.map((m) => {
              const mine = (m.author_is_client && isClient) || (!m.author_is_client && !isClient);
              return (
                <div key={m.id} ref={(el) => (messageRefs.current[m.id] = el)} className={`flex ${mine ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[80%] p-2 rounded-lg text-sm ${mine ? "bg-[#0F6B4A] text-white" : "bg-white border border-border"}`}>
                    <div className={`text-[10px] mb-0.5 ${mine ? "text-white/70" : "text-muted-foreground"}`}>
                      {m.author_name} · {m.created_at?.slice(11, 16)}
                    </div>
                    {m.media_kind === "image" && m.media_url && (
                      <img src={m.media_url.startsWith("http") ? m.media_url : `${API}${m.media_url}`} alt="" className="max-w-full rounded mb-1" style={{maxHeight: 200}} />
                    )}
                    {m.body && <div className="whitespace-pre-wrap">{m.body}</div>}
                  </div>
                </div>
              );
            })}
          </div>

          {activeThread && (
            <div className="p-2 border-t border-border flex gap-2 bg-white md:rounded-b-xl">
              <div className="flex flex-col gap-1">
                <button
                  onClick={pickPhoto}
                  disabled={uploadingPhoto}
                  className="h-8 w-8 rounded bg-slate-100 hover:bg-slate-200 flex items-center justify-center"
                  data-testid="chat-photo-btn" title="Envoyer une photo"
                >
                  {uploadingPhoto ? <Loader2 className="w-4 h-4 animate-spin" /> : <Camera className="w-4 h-4" />}
                </button>
                <input ref={fileInputRef} type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => uploadPhoto(e.target.files?.[0])} data-testid="chat-photo-input" />
                <button
                  onClick={recording ? stopRecording : startRecording}
                  disabled={transcribing}
                  className={`h-8 w-8 rounded flex items-center justify-center ${recording ? "bg-red-100 hover:bg-red-200" : "bg-slate-100 hover:bg-slate-200"}`}
                  data-testid="chat-voice-btn" title={recording ? "Arrêter" : "Note vocale"}
                >
                  {transcribing ? <Loader2 className="w-4 h-4 animate-spin" /> : (recording ? <Square className="w-4 h-4 text-red-600" /> : <Mic className="w-4 h-4" />)}
                </button>
              </div>
              <Textarea
                rows={2}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                placeholder={recording ? "Enregistrement en cours…" : transcribing ? "Transcription…" : "Écrire un message… (Entrée pour envoyer)"}
                className="text-sm resize-none min-h-[40px]"
                data-testid="chat-bubble-body-input"
              />
              <Button onClick={send} disabled={!body.trim()} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white self-stretch px-3" data-testid="chat-bubble-send-btn">
                <Send className="w-4 h-4" />
              </Button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
