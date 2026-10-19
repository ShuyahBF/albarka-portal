import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import {
  MessageCircle, Reply, Send, Loader2, Search, RefreshCw, ArrowLeft,
  Image as ImageIcon, Mic, FileText, MapPin, Video, Check, CheckCheck, AlertTriangle,
  Zap, Plus, Trash2, Pencil, Tag, BellRing, BellOff, BarChart3, UserPlus,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient, extractError } from "@/lib/api";
import { PresenceDot, PresenceLabel } from "@/components/Presence";
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
// Même compte que ADMIN_ACCOUNT_EMAIL côté serveur (albarka_models.py) : seul lui peut vider les conversations
const ADMIN_ACCOUNT_EMAIL = "admin@sawalismartsystems.com";

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
  const { user } = useAuth();
  const isSuperAdmin = (user?.email || "").toLowerCase() === ADMIN_ACCOUNT_EMAIL;
  const [purgeOuvert, setPurgeOuvert] = useState(false);       // fenêtre de confirmation « Vider les conversations »
  const [purgeTexte, setPurgeTexte] = useState("");
  const [purgeEnCours, setPurgeEnCours] = useState(false);
  const [conversations, setConversations] = useState([]);
  const [loadingList, setLoadingList] = useState(true);
  const [selectedPhone, setSelectedPhone] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [citation, setCitation] = useState(null);                // lot 38 : message auquel on répond (« Répondre » sur une bulle)
  const signatureMsgsRef = useRef("");                           // lot 38 : empreinte des messages affichés (évite les rafraîchissements inutiles)
  const signatureConvsRef = useRef("");
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [q, setQ] = useState("");
  const [labelFilter, setLabelFilter] = useState("all");
  const [notifEnabled, setNotifEnabled] = useState(() => localStorage.getItem(LS_NOTIF) !== "0");
  const [quickReplies, setQuickReplies] = useState([]);
  const [qrDialogOpen, setQrDialogOpen] = useState(false);
  const [horsFenetre, setHorsFenetre] = useState(false);   // lot 39 : confirmation d'envoi hors fenêtre de 24 h
  const [qrEditing, setQrEditing] = useState(null); // {id?, label, body}
  const [qrSaving, setQrSaving] = useState(false);
  const [newConvOpen, setNewConvOpen] = useState(false);
  const [contacts, setContacts] = useState([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  // Vue de gauche : « contacts » (liste propre au cabinet, vue par défaut) ou « conversations » (toutes les discussions)
  const [vue, setVue] = useState("contacts");
  const [cabContacts, setCabContacts] = useState([]);
  const [cabLoading, setCabLoading] = useState(true);
  const [nouveauContact, setNouveauContact] = useState(false);   // formulaire de création ouvert
  const [nc, setNc] = useState({ full_name: "", phone: "", organization: "" });
  const [ncSaving, setNcSaving] = useState(false);
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
      // Lot 38 : la liste n'est redessinée que si elle a réellement changé (plus de « tremblement » à chaque rafraîchissement)
      const signature = JSON.stringify(data);
      if (signature !== signatureConvsRef.current) { signatureConvsRef.current = signature; setConversations(data); }
    } catch (err) { toast.error(extractError(err)); }
    finally { setLoadingList(false); }
  };

  // Lot 38 : un rafraîchissement automatique (`silent`) n'affiche plus « Chargement… », ne redessine la conversation que si elle a
  // changé, et ne fait défiler vers le bas que lorsqu'un NOUVEAU message arrive : fini les oscillations verticales.
  const loadMessages = async (phone, { silent = false } = {}) => {
    if (!phone) return;
    if (!silent) setLoadingMsgs(true);
    try {
      const { data } = await apiClient.get(`/whatsapp/conversations/${encodeURIComponent(phone)}/messages`);
      const signature = JSON.stringify(data.map((m) => [m.id, m.wa_status, m.wa_status_at, m.body]));
      const dernierId = data.length ? data[data.length - 1].id : "";
      const nouveauMessage = !signatureMsgsRef.current || !signatureMsgsRef.current.endsWith(`|${dernierId}`);
      if (signature + `|${dernierId}` !== signatureMsgsRef.current) {
        signatureMsgsRef.current = `${signature}|${dernierId}`;
        setMessages(data);
        if (!silent || nouveauMessage) setTimeout(() => scrollRef.current?.scrollTo({ top: 9e9, behavior: silent ? "auto" : "smooth" }), 60);
      }
      if (!silent) loadConversations({ notify: false });
    } catch (err) { if (!silent) toast.error(extractError(err)); }
    finally { if (!silent) setLoadingMsgs(false); }
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

  // --- Contacts du cabinet : liste, création sur place, ouverture d'un fil ---
  const loadCabinetContacts = async () => {
    try {
      const { data } = await apiClient.get("/contacts");
      setCabContacts((data || []).filter((c) => c.scope === "cabinet"));
    } catch (err) { toast.error(extractError(err, "Impossible de charger les contacts du cabinet")); }
    finally { setCabLoading(false); }
  };

  // Numéro au format international : 8 chiffres → +226 (Burkina Faso), « 00… » → « +… »
  const normaliserTel = (v) => {
    const t = (v || "").replace(/[\s.\-()]/g, "");
    if (/^\d{8}$/.test(t)) return `+226${t}`;
    if (t.startsWith("00")) return `+${t.slice(2)}`;
    return t;
  };

  // Crée le contact du cabinet (WhatsApp activé) puis ouvre directement son fil de conversation
  const creerContactCabinet = async (e) => {
    e.preventDefault();
    const phone = normaliserTel(nc.phone);
    if (!/^\+\d{8,15}$/.test(phone)) { toast.error("Numéro invalide : 8 chiffres (Burkina) ou format international +226…"); return; }
    setNcSaving(true);
    try {
      const { data } = await apiClient.post("/contacts", {
        scope: "cabinet", full_name: nc.full_name.trim(), phone, organization: nc.organization.trim() || null,
        function: "autre", channels: ["whatsapp"],
      });
      toast.success("Contact créé");
      setNc({ full_name: "", phone: "", organization: "" });
      setNouveauContact(false);
      await loadCabinetContacts();
      startConversation({ ...data, full_name: data?.full_name || nc.full_name.trim(), phone });
    } catch (err) { toast.error(extractError(err, "Création impossible")); }
    finally { setNcSaving(false); }
  };

  // Clé de rapprochement contact ↔ conversation : les 8 derniers chiffres du numéro
  const cle8 = (t) => (t || "").replace(/\D/g, "").slice(-8);
  const convParCle = useMemo(() => {
    const m = {};
    conversations.forEach((c) => { m[cle8(c.phone)] = c; });
    return m;
  }, [conversations]);

  const contactsFiltres = useMemo(() => {
    const term = q.trim().toLowerCase();
    return cabContacts.filter((c) => !term || `${c.full_name} ${c.organization || ""} ${c.phone || ""}`.toLowerCase().includes(term));
  }, [cabContacts, q]);

  const ouvrirContact = (c) => {
    if (!(c.phone || "").trim()) { toast.error("Ce contact n'a pas de numéro : complétez-le dans le module Contacts."); return; }
    const phone = c.phone.trim();
    const existante = convParCle[cle8(phone)];
    startConversation({ ...c, phone: existante?.phone || phone });
  };

  // Super-admin : vide TOUTES les conversations (messages et étiquettes) après saisie de « SUPPRIMER »
  const purgerConversations = async () => {
    setPurgeEnCours(true);
    try {
      const { data } = await apiClient.post("/whatsapp/conversations/purge", { confirmation: purgeTexte.trim() });
      toast.success(`Conversations vidées : ${data.messages_supprimes} message(s) supprimé(s)`);
      setPurgeOuvert(false); setPurgeTexte(""); setSelectedPhone(null); setMessages([]);
      await loadConversations({ notify: false });
    } catch (err) { toast.error(extractError(err, "Suppression impossible")); }
    finally { setPurgeEnCours(false); }
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

  useEffect(() => { loadConversations({ notify: false }); loadQuickReplies(); loadCabinetContacts(); /* eslint-disable-next-line */ }, []);
  useEffect(() => {
    const t = setInterval(() => {
      loadConversations();
      if (selectedPhone) loadMessages(selectedPhone, { silent: true });
    }, POLL_MS);
    return () => clearInterval(t);
    // eslint-disable-next-line
  }, [selectedPhone, notifEnabled]);

  useEffect(() => { signatureMsgsRef.current = ""; setCitation(null); if (selectedPhone) loadMessages(selectedPhone); /* eslint-disable-next-line */ }, [selectedPhone]);

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

  // Présence portail des contacts qui sont des clients (par numéro, toutes les 15 s)
  const [portalPresence, setPortalPresence] = useState({});
  const phonesKey = conversations.map((c) => c.phone).slice(0, 200).join(",");
  useEffect(() => {
    if (!phonesKey) return undefined;
    let alive = true;
    const load = () => apiClient.get("/presence/by-phone", { params: { phones: phonesKey.split(",") }, paramsSerializer: { indexes: null } })
      .then(({ data }) => { if (alive) setPortalPresence(data.items || {}); }).catch(() => {});
    load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, [phonesKey]);

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

  // Lot 39 : `confirmer` = true quand le cabinet a accepté l'envoi hors fenêtre de 24 h (modèle Meta facturé)
  const send = async (confirmer = false) => {
    if (!reply.trim() || !selectedPhone) return;
    setSending(true);
    try {
      const { data } = await apiClient.post(
        `/whatsapp/conversations/${encodeURIComponent(selectedPhone)}/reply`,
        { body: reply.trim(), ...(citation ? { reply_to_id: citation.id } : {}), ...(confirmer ? { confirmer_modele: true } : {}) },
      );
      if (data?.result?.outside_24h_window) toast.warning("Message envoyé hors fenêtre 24h — Meta peut le refuser.");
      else if (!data?.ok) toast.error(data?.result?.error || "Envoi refusé par Meta");
      else toast.success("Réponse envoyée");
      setReply(""); setCitation(null); setHorsFenetre(false);
      await Promise.all([loadMessages(selectedPhone, { silent: true }), loadConversations({ notify: false })]);
    } catch (err) {
      // 409 « hors_fenetre_24h » : on demande d'abord l'accord du cabinet (facturation du modèle Meta)
      if (err?.response?.status === 409 && err.response.data?.detail?.code === "hors_fenetre_24h") setHorsFenetre(true);
      else toast.error(extractError(err));
    }
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
        {/* Lot 43 : les boutons passent à la ligne sur mobile (sinon la page déborde à droite) */}
        <div className="flex flex-wrap items-center gap-2 max-w-full">
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
          {isSuperAdmin && (
            <Button variant="outline" size="sm" onClick={() => setPurgeOuvert(true)} className="text-red-700 border-red-200" data-testid="wa-inbox-purge-btn">
              <Trash2 className="w-4 h-4 mr-1" /> Vider les conversations
            </Button>
          )}
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
            {/* Onglets : liste de contacts du cabinet (par défaut) / toutes les conversations */}
            <div className="flex gap-1" role="tablist">
              {[{ v: "contacts", t: "Contacts du cabinet" }, { v: "conversations", t: "Conversations", n: totalUnread }].map((o) => (
                <button key={o.v} role="tab" aria-selected={vue === o.v} onClick={() => setVue(o.v)}
                  className={`flex-1 text-xs px-2 py-1.5 rounded border ${vue === o.v ? "bg-[#0F6B4A] text-white border-[#0F6B4A]" : "bg-white border-slate-200 hover:bg-slate-50"}`}
                  data-testid={`wa-inbox-tab-${o.v}`}>
                  {o.t}{o.n > 0 && <span className="ml-1 rounded-full bg-[#E5A24B] px-1.5 text-[10px] text-white">{o.n}</span>}
                </button>
              ))}
            </div>
            <div className="relative">
              <Search className="w-4 h-4 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder={vue === "contacts" ? "Rechercher un contact du cabinet…" : "Rechercher numéro, contact, message…"}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                className="pl-8 h-9"
                data-testid="wa-inbox-search-input"
              />
            </div>
            {/* Filtre par étiquette */}
            <div className={`flex items-center gap-1 flex-wrap ${vue === "contacts" ? "hidden" : ""}`}>
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
          {vue === "contacts" && (
            <div className="flex-1 overflow-y-auto" data-testid="wa-inbox-contacts">
              {/* Création d'un contact du cabinet sur place, sans quitter la messagerie */}
              <div className="p-2 border-b border-slate-100">
                {!nouveauContact ? (
                  <Button size="sm" variant="outline" className="w-full" onClick={() => setNouveauContact(true)} data-testid="wa-inbox-new-contact-btn">
                    <UserPlus className="w-4 h-4 mr-1" /> Nouveau contact
                  </Button>
                ) : (
                  <form onSubmit={creerContactCabinet} className="space-y-2" data-testid="wa-inbox-new-contact-form">
                    <Input required placeholder="Nom du contact" value={nc.full_name} onChange={(e) => setNc({ ...nc, full_name: e.target.value })} className="h-9" data-testid="wa-inbox-nc-name" />
                    <Input required placeholder="Téléphone (ex. 70 00 00 00 ou +226…)" value={nc.phone} onChange={(e) => setNc({ ...nc, phone: e.target.value })} className="h-9" data-testid="wa-inbox-nc-phone" />
                    <Input placeholder="Société (facultatif)" value={nc.organization} onChange={(e) => setNc({ ...nc, organization: e.target.value })} className="h-9" />
                    <div className="flex gap-2">
                      <Button type="submit" size="sm" disabled={ncSaving} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="wa-inbox-nc-save">
                        {ncSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : "Créer et écrire"}
                      </Button>
                      <Button type="button" size="sm" variant="outline" onClick={() => setNouveauContact(false)}>Annuler</Button>
                    </div>
                  </form>
                )}
              </div>
              {cabLoading && <div className="p-6 text-center text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin inline mr-2" />Chargement…</div>}
              {!cabLoading && contactsFiltres.length === 0 && (
                <div className="p-6 text-center text-sm text-muted-foreground">Aucun contact du cabinet. Utilisez « Nouveau contact ».</div>
              )}
              {contactsFiltres.map((c) => {
                const conv = convParCle[cle8(c.phone)];
                const actif = conv && conv.phone === selectedPhone;
                return (
                  <button key={c.id} onClick={() => ouvrirContact(c)}
                    className={`w-full text-left px-3 py-2.5 border-b border-slate-100 hover:bg-slate-50 transition ${actif ? "bg-emerald-50" : ""}`}
                    data-testid={`wa-inbox-contact-${c.id}`}>
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-medium text-sm truncate">{c.full_name}</div>
                      <div className="text-[10px] text-muted-foreground shrink-0">{conv ? fmtDate(conv.last_at) : ""}</div>
                    </div>
                    <div className="flex items-center justify-between gap-2 mt-0.5">
                      <div className="text-xs text-muted-foreground truncate">
                        {conv ? preview(conv) || c.phone : `${c.phone || "Sans numéro"} · nouvelle conversation`}
                      </div>
                      {conv?.unread > 0 && <Badge className="bg-[#E5A24B] text-white h-5 min-w-5 px-1.5 text-[10px]">{conv.unread}</Badge>}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
          <div className={`flex-1 overflow-y-auto ${vue === "contacts" ? "hidden" : ""}`} data-testid="wa-inbox-list">
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
                      {/* Client connecté au portail en ce moment */}
                      {portalPresence[c.phone] && portalPresence[c.phone].status !== "offline" && <PresenceDot presence={portalPresence[c.phone]} />}
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
                <div className="text-sm">Sélectionnez un contact (ou une conversation) pour afficher l'historique et écrire.</div>
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
                  <div className="text-[11px] opacity-80 flex items-center gap-2">
                    {selectedPhone}
                    {/* Présence sur le portail (contact = client du cabinet) */}
                    {portalPresence[selectedPhone] && <span className="bg-white rounded px-1.5 py-0.5" data-testid="wa-portal-presence"><PresenceLabel presence={portalPresence[selectedPhone]} /></span>}
                  </div>
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
                          {/* Lot 38 : « Répondre » à ce message (citation) */}
                          <button type="button" onClick={() => setCitation(m)} title="Répondre à ce message" aria-label="Répondre à ce message"
                            className="mr-1 opacity-70 hover:opacity-100" data-testid={`wa-msg-repondre-${m.id}`}>
                            <Reply className="w-3 h-3" />
                          </button>
                          <span>{outbound ? (m.sent_by_name || "Cabinet") : (m.contact_name || m.profile_name || m.phone)}</span>
                          <span>·</span>
                          <span>{m.created_at?.slice(11, 16)}</span>
                          {outbound && m.wa_error && (
                            <span title={m.wa_error} className="ml-1"><AlertTriangle className="w-3 h-3 text-amber-300" /></span>
                          )}
                          {outbound && !m.wa_error && !m.wa_status && <Check className="w-3 h-3 ml-1" />}   {/* l'état détaillé sous le message remplace cette coche */}
                          {/* Lot 35 : plus de mention « via Liluvine » — confidentialité des échanges du cabinet avec ses clients */}
                        </div>
                        {/* Lot 38 : message cité par cette réponse */}
                        {m.reply_to && (
                          <div className={`mb-1 rounded border-l-4 px-2 py-1 text-[11px] ${outbound ? "bg-white/15 border-white/60" : "bg-slate-100 border-[#0F6B4A]"}`} data-testid={`wa-msg-citation-${m.id}`}>
                            <div className="font-semibold">{m.reply_to.auteur}</div>
                            <div className="line-clamp-2 opacity-90">{m.reply_to.texte}</div>
                          </div>
                        )}
                        {m.message_type === "location" && <div className="italic opacity-80">📍 Localisation partagée</div>}
                        {["image", "video", "audio", "document"].includes(m.message_type) && !m.body && !m.voice_note_transcript && (
                          <div className="italic opacity-80">
                            [{m.message_type}{m.media_mime ? ` · ${m.media_mime}` : ""}]
                          </div>
                        )}
                        {/* Lot 13.9 : média d'une réponse via Liluvine (lien temporaire fourni par SAWALI) */}
                        {m.via_liluvine && m.media_url?.startsWith("https://") && (
                          <a href={m.media_url} target="_blank" rel="noopener noreferrer" className="underline text-xs block mb-1">
                            Ouvrir le fichier{m.media_filename ? ` (${m.media_filename})` : ""}
                          </a>
                        )}
                        {m.voice_note_transcript && (
                          <div className={`italic ${outbound ? "text-white/90" : "text-slate-600"} mb-1`}>🎙️ {m.voice_note_transcript}</div>
                        )}
                        {m.body && <div className="whitespace-pre-wrap break-words">{m.body}</div>}
                        {/* Lot 35 : état de l'envoi sous le message — Transmis, Distribué, Lu (avec l'heure de chaque étape) ou Échec */}
                        {outbound && m.wa_status && (
                          <div className="text-[10px] mt-1 text-white/80 flex flex-wrap items-center gap-x-2" data-testid={`wa-msg-etat-${m.id}`}>
                            {m.wa_status === "failed" ? (
                              <span className="text-amber-300">✗ Échec{m.wa_status_error ? ` : ${m.wa_status_error}` : ""}</span>
                            ) : (
                              [["sent", "Transmis", 1], ["delivered", "Distribué", 2], ["read", "Lu", 3]]
                                .filter(([cle, , rang]) => (m.wa_status_times || {})[cle] || { sent: 1, delivered: 2, read: 3 }[m.wa_status] >= rang)
                                .map(([cle, libelle, rang]) => {
                                  const quand = (m.wa_status_times || {})[cle] || (m.wa_status === cle ? m.wa_status_at : null);
                                  return (
                                    <span key={cle} className={`inline-flex items-center gap-1 ${cle === "read" ? "text-sky-200" : ""}`}>
                                      {/* Une coche pour Transmis et Distribué ; la double coche (chevauchée, bleue) est réservée à Lu */}
                                      {rang < 3 ? <Check className="w-3.5 h-3.5" /> : <CheckCheck className="w-3.5 h-3.5" />}
                                      {libelle}{quand ? ` ${quand.slice(11, 16)}` : ""}
                                    </span>
                                  );
                                })
                            )}
                          </div>
                        )}
                        {outbound && m.outside_24h_window && (
                          <div className="text-[10px] mt-1 text-amber-300">Hors fenêtre 24h</div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="p-2 border-t border-border bg-white flex flex-wrap gap-2 items-stretch">
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
                {citation && (
                  <div className="order-first flex w-full items-start gap-2 rounded-md border bg-slate-50 px-2 py-1 text-xs" data-testid="wa-inbox-citation-barre">
                    <Reply className="w-3 h-3 mt-0.5 shrink-0 text-[#0F6B4A]" />
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold truncate">{citation.direction === "outbound" ? (citation.sent_by_name || "Cabinet") : (citation.contact_name || citation.profile_name || citation.phone)}</div>
                      <div className="truncate text-muted-foreground">{citation.body || citation.voice_note_transcript || `[${citation.message_type}]`}</div>
                    </div>
                    <button type="button" onClick={() => setCitation(null)} aria-label="Annuler la citation" className="text-slate-500 hover:text-slate-800">✕</button>
                  </div>
                )}
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
                  onClick={() => send(false)}
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

      {/* Lot 39 — confirmation : envoi hors fenêtre de 24 h = modèle Meta facturé au cabinet */}
      <Dialog open={horsFenetre} onOpenChange={setHorsFenetre}>
        <DialogContent data-testid="wa-inbox-hors-fenetre-dialog">
          <DialogHeader>
            <DialogTitle>Envoyer hors de la fenêtre de 24 h ?</DialogTitle>
            <DialogDescription className="text-xs">
              Ce contact ne vous a pas écrit depuis plus de 24 h. Le message partira avec un modèle Meta approuvé,
              et Meta facture chaque modèle envoyé au cabinet.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setHorsFenetre(false)} data-testid="wa-inbox-hors-fenetre-annuler">Annuler</Button>
            <Button onClick={() => send(true)} disabled={sending} data-testid="wa-inbox-hors-fenetre-confirmer">Envoyer avec un modèle (facturé)</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Dialog de confirmation — vider toutes les conversations (super-admin) */}
      <Dialog open={purgeOuvert} onOpenChange={(o) => { setPurgeOuvert(o); if (!o) setPurgeTexte(""); }}>
        <DialogContent data-testid="wa-inbox-purge-dialog">
          <DialogHeader>
            <DialogTitle>Vider toutes les conversations WhatsApp ?</DialogTitle>
            <DialogDescription className="text-xs">
              Tous les messages et toutes les étiquettes de cette messagerie seront supprimés définitivement. Les contacts, les réponses rapides
              et les messages déjà reçus sur les téléphones ne sont pas touchés. Tapez <b>SUPPRIMER</b> pour confirmer.
            </DialogDescription>
          </DialogHeader>
          <Input value={purgeTexte} onChange={(e) => setPurgeTexte(e.target.value)} placeholder="SUPPRIMER" data-testid="wa-inbox-purge-input" />
          <DialogFooter>
            <Button variant="outline" onClick={() => setPurgeOuvert(false)}>Annuler</Button>
            <Button onClick={purgerConversations} disabled={purgeEnCours || purgeTexte.trim().toUpperCase() !== "SUPPRIMER"}
              className="bg-red-700 hover:bg-red-800 text-white" data-testid="wa-inbox-purge-confirm">
              {purgeEnCours ? <Loader2 className="w-4 h-4 animate-spin" /> : "Vider définitivement"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
