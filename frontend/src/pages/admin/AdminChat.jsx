import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, MessageSquare, Send } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/AuthContext";

/**
 * AdminChat — messagerie interne staff ⇄ client, thread par client.
 * Un client ne peut voir que son propre thread ("client:<id>").
 * Un membre du cabinet voit tous les threads (liste par client).
 */
export default function AdminChat() {
  const [threads, setThreads] = useState([]);
  const [activeThread, setActiveThread] = useState(null);
  const [messages, setMessages] = useState([]);
  const [body, setBody] = useState("");
  const [clients, setClients] = useState([]);
  const [newTenantId, setNewTenantId] = useState("");
  const { user, isClient } = useAuth();

  const loadThreads = async () => {
    try {
      if (isClient) {
        setThreads([{ thread_id: `client:${user.id}`, last_at: null, last_author: "", last_body: "", count: 0 }]);
        setActiveThread(`client:${user.id}`);
      } else {
        const [{ data: t }, { data: c }] = await Promise.all([
          apiClient.get("/chat/threads"),
          apiClient.get("/clients"),
        ]);
        setThreads(t); setClients(c);
        if (t.length && !activeThread) setActiveThread(t[0].thread_id);
      }
    } catch (err) { toast.error(extractError(err)); }
  };

  const clientNameFromThread = (threadId) => {
    if (!threadId) return "";
    const id = threadId.startsWith("client:") ? threadId.slice(7) : threadId;
    const c = clients.find((x) => x.id === id);
    return c ? `${c.full_name}${c.company ? ` — ${c.company}` : ""}` : threadId;
  };

  const loadMessages = async () => {
    if (!activeThread) return;
    try {
      const { data } = await apiClient.get("/chat/messages", { params: { thread_id: activeThread } });
      setMessages(data);
    } catch (err) { toast.error(extractError(err)); }
  };

  useEffect(() => { loadThreads(); }, []);
  useEffect(() => { loadMessages(); }, [activeThread]);

  const send = async () => {
    if (!body.trim() || !activeThread) return;
    try {
      await apiClient.post("/chat/messages", { thread_id: activeThread, body: body.trim() });
      setBody("");
      await Promise.all([loadMessages(), loadThreads()]);
    } catch (err) { toast.error(extractError(err)); }
  };

  const startThread = () => {
    if (!newTenantId) { toast.error("Sélectionnez un client"); return; }
    const newThread = `client:${newTenantId}`;
    setActiveThread(newThread);
    // Ajoute localement si absent, sera confirmé au prochain loadThreads
    setThreads((prev) => prev.some((t) => t.thread_id === newThread) ? prev : [{ thread_id: newThread, last_at: null, last_author: "", last_body: "(nouveau fil)", count: 0 }, ...prev]);
    setNewTenantId("");
  };

  return (
    <div className="space-y-6" data-testid="admin-chat-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Communication</div>
        <h1 className="font-display text-3xl md:text-4xl">Chat interne</h1>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 min-h-[500px]">
        {/* Sidebar threads */}
        <div className="md:col-span-1 albarka-card p-3 space-y-2">
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">Fils</div>
          {!isClient && (
            <div className="space-y-1 mb-3">
              <select className="w-full h-9 rounded-md border border-input px-2 text-xs" value={newTenantId} onChange={(e) => setNewTenantId(e.target.value)} data-testid="chat-new-tenant-select">
                <option value="">-- Nouveau fil client --</option>
                {clients.map((c) => (<option key={c.id} value={c.id}>{c.full_name}</option>))}
              </select>
              <Button size="sm" variant="outline" className="w-full h-8" onClick={startThread} data-testid="chat-start-thread-btn"><Plus className="w-3 h-3 mr-1" />Ouvrir le fil</Button>
            </div>
          )}
          {threads.length === 0 && <div className="text-xs text-muted-foreground py-4 text-center">Aucun fil.</div>}
          {threads.map((t) => (
            <button
              key={t.thread_id}
              onClick={() => setActiveThread(t.thread_id)}
              className={`w-full text-left p-2 rounded hover:bg-[#0F6B4A]/5 ${activeThread === t.thread_id ? "bg-[#0F6B4A]/10 border border-[#0F6B4A]/30" : ""}`}
              data-testid={`chat-thread-${t.thread_id}`}
            >
              <div className="text-sm font-medium truncate">{isClient ? "Mon cabinet" : clientNameFromThread(t.thread_id)}</div>
              <div className="text-[11px] text-muted-foreground truncate">{t.last_body || "—"}</div>
            </button>
          ))}
        </div>

        {/* Messages panel */}
        <div className="md:col-span-3 albarka-card flex flex-col">
          <div className="p-3 border-b border-border flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-[#0F6B4A]" />
            <span className="text-sm font-medium">{activeThread ? (isClient ? "Mon cabinet" : clientNameFromThread(activeThread)) : "Sélectionnez un fil"}</span>
          </div>
          <div className="flex-1 p-4 overflow-y-auto space-y-2 min-h-[350px]" data-testid="chat-messages-panel">
            {messages.length === 0 && <div className="text-xs text-muted-foreground text-center py-10">Aucun message.</div>}
            {messages.map((m) => (
              <div key={m.id} className={`max-w-[80%] p-2 rounded-lg text-sm ${m.author_is_client ? "bg-slate-100 mr-auto" : "bg-[#0F6B4A]/10 ml-auto"}`}>
                <div className="text-[10px] text-muted-foreground mb-0.5">{m.author_name} · {m.created_at?.slice(11, 16)}</div>
                <div>{m.body}</div>
              </div>
            ))}
          </div>
          <div className="p-3 border-t border-border flex gap-2">
            <Textarea rows={2} value={body} onChange={(e) => setBody(e.target.value)} placeholder="Écrire un message…" data-testid="chat-body-input" />
            <Button onClick={send} disabled={!body.trim() || !activeThread} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white h-auto" data-testid="chat-send-btn"><Send className="w-4 h-4" /></Button>
          </div>
        </div>
      </div>
    </div>
  );
}
