import React, { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  FileText,
  CalendarClock,
  Briefcase,
  Users,
  UserCog,
  Contact,
  Sprout,
  LogOut,
  Menu,
  X,
  History,
  Scale,
  Wallet,
  ClipboardList,
  Settings,
  FileSignature,
  MessageSquare,
  Receipt,
  Archive,
  Send,
  MessageCircle,
  BookOpen,
  ScrollText,
  Zap,
  CreditCard,
  ClipboardCheck,
  FolderOpen,
  FolderUp,
  FilePen,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api";
import ChatBubble from "@/components/ChatBubble";
import PaymentBubble from "@/components/PaymentBubble";
import { usePresenceHeartbeat, sendOffline } from "@/components/Presence";
import AutoLogoutGate from "@/components/AutoLogoutGate";
import SidebarInfoBar from "@/components/SidebarInfoBar";

// Actualisation des badges non-lus (WhatsApp/Diffusion) par polling — pas de
// WebSocket/SSE dans l'application, même convention que ChatBubble.jsx.
const BADGES_POLL_MS = 15000;

// Doit rester identique à PAYMENTS_ROLES côté backend (albarka_models.py).
const PAYMENTS_ROLES = ["caissier"];
// Doit rester identique à FORMS_ROLES côté backend (albarka_models.py).
const FORMS_ROLES = ["formulaires"];

// Client sidebar (unchanged for pure clients).
// `module` = clé du module (CLIENT_PORTAL_MODULES côté backend) que le cabinet
// peut fermer client par client ; sans `module`, le lien est toujours visible.
const CLIENT_LINKS = [
  { to: "/portal", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/portal/documents", label: "Mes pièces", icon: FileText, module: "documents" },
  // Factures, reçus, rapports… mis à disposition par le cabinet
  { to: "/portal/documents-cabinet", label: "Factures & documents", icon: FolderOpen, module: "cabinet_documents" },
  { to: "/portal/missions", label: "Mes missions", icon: Briefcase, module: "missions" },
  { to: "/portal/echeances", label: "Échéances", icon: CalendarClock, module: "echeances" },
  { to: "/portal/historique", label: "Historique", icon: History, module: "historique" },
  // Formulaires envoyés par le cabinet (à remplir / déjà répondus)
  { to: "/portal/formulaires", label: "Mes formulaires", icon: ClipboardCheck, module: "formulaires" },
  { to: "/portal/mon-compte", label: "Mon compte", icon: UserCog },
];
// Doit rester identique à CLIENT_SPACE_ROLES côté backend (albarka_models.py).
const CLIENT_SPACE_ROLES = ["administrateur", "direction", "dg", "secretariat", "comptable", "fiscaliste", "aide_comptable", "caissier"];

// Staff menu items with the roles that grant access. `superviseur` = full access.
const STAFF_MENU = [
  { to: "/admin", label: "Tableau de bord", icon: LayoutDashboard, end: true,
    roles: ["superviseur", "direction", "administrateur", "secretariat", "fiscaliste", "comptable", "aide_comptable", "rh"] },
  { to: "/admin/clients", label: "Clients", icon: Users,
    roles: ["superviseur", "direction", "administrateur", "secretariat"] },
  { to: "/admin/contacts", label: "Contacts", icon: Contact,
    roles: ["superviseur", "direction", "secretariat", "comptable", "fiscaliste"] },
  { to: "/admin/staff", label: "Personnels", icon: UserCog,
    roles: ["superviseur", "direction", "administrateur"] },
  { to: "/admin/documents", label: "Pièces", icon: FileText,
    roles: ["superviseur", "direction", "secretariat", "fiscaliste", "comptable", "aide_comptable", "rh"] },
  { to: "/admin/missions", label: "Missions", icon: Briefcase,
    roles: ["superviseur", "direction", "secretariat", "fiscaliste", "comptable", "aide_comptable"] },
  // Lot 7 : ordres / avis de mission, courriers… rédigés comme dans Word, modèles à variables
  { to: "/admin/modeles", label: "Documents & modèles", icon: FilePen,
    roles: ["superviseur", "direction", "administrateur", "secretariat", "fiscaliste", "comptable", "aide_comptable", "rh"] },
  { to: "/admin/echeances", label: "Échéances fiscales", icon: Scale,
    roles: ["superviseur", "direction", "secretariat", "fiscaliste", "comptable"] },
  { to: "/admin/paie", label: "Paie & RH", icon: Wallet,
    roles: ["superviseur", "direction", "administrateur", "rh"] },
  { to: "/admin/rapports", label: "Rapports client", icon: ClipboardList, end: true, // end : pas surligné sur « Rapports en masse »
    roles: ["superviseur", "direction", "secretariat", "comptable", "fiscaliste"] },
  { to: "/admin/rapports/bulk", label: "Rapports en masse", icon: Zap,
    roles: ["superviseur", "direction", "comptable", "fiscaliste"] },
  { to: "/admin/contrats", label: "Contrats clients", icon: FileSignature,
    roles: ["superviseur", "direction", "administrateur", "secretariat"] },
  // Caisse : le Caissier y accède aussi (seul habilité à encaisser / délivrer un reçu).
  { to: "/admin/caisse", label: "Caisse", icon: Receipt,
    roles: ["superviseur", "direction", "administrateur", "comptable", "secretariat", "caissier"] },
  // Réservé au rôle "caissier" — masqué pour tous les autres, y compris les
  // rôles Caisse ci-dessus (paiements mobile money, distinct de la caisse
  // manuelle). Le passe-droit "superviseur" standard reste appliqué.
  { to: "/admin/paiements", label: "Paiements", icon: CreditCard, roles: PAYMENTS_ROLES },
  // Formulaires : visible UNIQUEMENT pour les collaborateurs ayant coché le
  // rôle « Formulaires » dans leur fiche (plus le superviseur, passe-droit standard).
  { to: "/admin/forms", label: "Formulaires", icon: ClipboardCheck, roles: FORMS_ROLES },
  // Déposer des documents faits hors du portail dans l'espace d'un client
  { to: "/admin/espace-client", label: "Dépôt espace client", icon: FolderUp, roles: CLIENT_SPACE_ROLES },
  { to: "/admin/comptabilite", label: "Comptabilité OHADA", icon: BookOpen,
    roles: ["superviseur", "direction", "administrateur", "comptable", "aide_comptable", "fiscaliste"] },
  { to: "/admin/messagerie", label: "Diffusion", icon: Send, badgeKey: "diffusion_new",
    roles: ["superviseur", "direction", "administrateur", "communication"] },
  { to: "/admin/whatsapp", label: "WhatsApp", icon: MessageCircle, badgeKey: "wa_unread",
    roles: ["superviseur", "direction", "administrateur", "communication"] },
  { to: "/admin/archives", label: "Archives", icon: Archive,
    roles: ["superviseur", "direction", "administrateur", "secretariat", "fiscaliste", "comptable"] },
  { to: "/admin/logs", label: "Journal plateforme", icon: ScrollText,
    roles: ["superviseur", "direction", "administrateur"] },
  // Paramètres : Superviseur uniquement (SETTINGS_ROLES côté backend)
  { to: "/admin/settings", label: "Paramètres", icon: Settings, roles: ["superviseur"] },
  // Accessible à TOUT collaborateur, quel que soit son rôle (alwaysAllowed) —
  // voir allowedFor() ci-dessous.
  { to: "/admin/mon-compte", label: "Mon compte", icon: UserCog, alwaysAllowed: true },
];

function allowedFor(link, roles) {
  if (link.alwaysAllowed) return true;
  if (roles.includes("superviseur")) return true;
  // La DG a les mêmes liens que la Direction (droits identiques côté serveur)
  const effective = roles.includes("dg") ? [...roles, "direction"] : roles;
  return (link.roles || []).some((r) => effective.includes(r));
}

export default function PortalLayout({ admin = false }) {
  const { user, logout } = useAuth();
  // Keep-alive : signale au cabinet que ce compte (client ou collaborateur) est connecté
  usePresenceHeartbeat(!!user);
  const [openSidebar, setOpenSidebar] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const roles = user?.roles || [];
  // Adresse désignée par admin pour créer des accès temporaires : elle voit
  // « Personnels » (où se trouve le bouton), même sans le rôle Direction.
  const [canIssueTokens, setCanIssueTokens] = useState(false);
  useEffect(() => {
    if (!admin) return;
    apiClient.get("/access/me").then(({ data }) => setCanIssueTokens(!!data.can_issue_tokens)).catch(() => {});
  }, [admin]);
  const links = admin
    ? STAFF_MENU.filter((l) => allowedFor(l, roles) || (canIssueTokens && l.to === "/admin/staff"))
    // Espace client : seuls les modules ouverts par le cabinet (aucun réglage = tous)
    : CLIENT_LINKS.filter((l) => !l.module || !Array.isArray(user?.portal_modules) || user.portal_modules.includes(l.module));
  // Rôle sans « Tableau de bord » dans son menu (ex. Caissier, Communication,
  // Formulaires) : à l'arrivée sur /admin, on ouvre son premier lien autorisé.
  useEffect(() => {
    if (admin && location.pathname === "/admin" && links.length && !links.some((l) => l.to === "/admin")) {
      navigate(links[0].to, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [admin, location.pathname, links.length]);
  const canUsePayments = roles.includes("superviseur") || roles.some((r) => PAYMENTS_ROLES.includes(r));

  // Badges non-lus (WhatsApp/Diffusion) affichés à côté du lien correspondant
  // dans le menu — voir albarka_badges.py. Uniquement côté staff (admin).
  const [badges, setBadges] = useState({});
  useEffect(() => {
    if (!admin) return;
    let cancelled = false;
    const refresh = () => {
      apiClient.get("/me/badges").then(({ data }) => { if (!cancelled) setBadges(data); }).catch(() => {});
    };
    refresh();
    const id = setInterval(refresh, BADGES_POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, [admin]);

  const markSeen = (page) => {
    apiClient.post("/me/badges/mark-seen", { page }).catch(() => {});
    setBadges((b) => ({ ...b, [`${page === "diffusion" ? "diffusion_new" : page}`]: 0 }));
  };

  // Thème « portail » (design SAWALI) : classe sur <body> pour couvrir aussi
  // les fenêtres rendues hors de la page ; retirée en quittant le portail.
  useEffect(() => {
    document.body.classList.add("portal-ui");
    return () => document.body.classList.remove("portal-ui");
  }, []);

  const handleLogout = async () => {
    await sendOffline(); // hors ligne tout de suite, avant de perdre le jeton
    logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-slate-50 flex">
      {/* Sidebar */}
      <aside
        data-testid="portal-sidebar"
        // La hauteur n'est plus donnée par une unité vh/dvh (peu fiable selon les
        // navigateurs mobiles : sur certains, la sidebar restait plus courte que la
        // fenêtre visible réelle, laissant un espace en bas). En `fixed` (mobile),
        // `top-0 bottom-0` ancre le bloc directement aux deux bords de l'écran —
        // exactement comme le voile de fond `fixed inset-0` juste en dessous, qui
        // lui s'affichait déjà correctement — donc la hauteur est déduite par le
        // navigateur, sans dépendre d'aucune unité de viewport. En `md:sticky`
        // (desktop), on revient à `h-screen`, sans le souci de barre d'adresse
        // mobile qui rétrécit/agrandit la fenêtre visible.
        className={`fixed md:sticky top-0 bottom-0 md:bottom-auto md:h-screen z-40 w-64 bg-[#0B1912] text-white flex-shrink-0 flex flex-col transition-transform md:translate-x-0 ${
          openSidebar ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {/* Barre jaune : date/heure en temps réel à gauche, n° de version à droite */}
        <SidebarInfoBar />
        <div className="px-5 py-6 border-b border-white/10 flex items-center gap-2.5 shrink-0">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-[#0F6B4A] to-[#E5A24B] flex items-center justify-center">
            <Sprout className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="font-display text-lg leading-tight">ALBARKA</div>
            <div className="text-[10px] uppercase tracking-widest text-white/50">
              {admin ? "Cabinet" : "Espace client"}
            </div>
          </div>
        </div>
        {/* flex-1 + min-h-0 (au lieu d'un max-h calculé en dur) : le menu prend
            exactement l'espace restant, quelle que soit la hauteur réelle du
            bloc utilisateur ci-dessous — un compte cumulant beaucoup de rôles
            (les badges passent sur plusieurs lignes) ne fait plus recouvrir
            les derniers liens (ex. "Paramètres") par ce bloc, qui était
            positionné en `absolute` par-dessus le menu. */}
        <nav className="flex-1 min-h-0 overflow-y-auto p-3 space-y-1">
          {links.map((link) => {
            const count = link.badgeKey ? badges[link.badgeKey] : 0;
            return (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) => `albarka-sidebar-link ${isActive ? "active" : ""}`}
              onClick={() => {
                setOpenSidebar(false);
                if (link.badgeKey === "diffusion_new") markSeen("diffusion");
              }}
              data-testid={`sidebar-link-${link.label.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}
            >
              <link.icon className="w-4 h-4" />
              <span className="flex-1">{link.label}</span>
              {!!count && (
                <span
                  className="ml-auto min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-semibold flex items-center justify-center"
                  data-testid={`sidebar-badge-${link.badgeKey}`}
                >
                  {count > 99 ? "99+" : count}
                </span>
              )}
            </NavLink>
            );
          })}
        </nav>
        <div className="shrink-0 p-4 border-t border-white/10 bg-[#0B1912]">
          <div className="text-xs text-white/70 mb-1 truncate font-medium">{user?.full_name}</div>
          <div className="flex flex-wrap gap-1 mb-2">
            {(user?.roles || []).map((r) => (
              <span key={r} className="text-[9px] uppercase tracking-wider bg-white/10 text-[#E5A24B] px-1.5 py-0.5 rounded" data-testid={`role-badge-${r}`}>
                {r.replace("_", " ")}
              </span>
            ))}
          </div>
          {user?.last_login && (
            <div
              className="text-[10px] text-white/50 mb-2 leading-tight"
              data-testid="sidebar-last-login"
              title={user.last_login}
            >
              Dernière connexion :{" "}
              {new Date(user.last_login).toLocaleString("fr-FR", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
            </div>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleLogout}
            className="w-full border-white/20 text-white bg-transparent hover:bg-white/10 hover:text-[#E5A24B]"
            data-testid="logout-btn"
          >
            <LogOut className="w-4 h-4 mr-2" />
            Déconnexion
          </Button>
        </div>
      </aside>

      {openSidebar && (
        <div
          className="md:hidden fixed inset-0 bg-black/50 z-30"
          onClick={() => setOpenSidebar(false)}
        />
      )}

      {/* Content */}
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="sticky top-0 z-20 bg-white/95 backdrop-blur border-b border-[hsl(var(--border))]">
          <div className="flex items-center justify-between px-5 py-3 md:px-8">
            <div className="flex items-center gap-3">
              <button
                className="md:hidden p-2 rounded-lg hover:bg-black/5"
                onClick={() => setOpenSidebar((v) => !v)}
                aria-label="Menu"
                data-testid="topbar-menu-toggle"
              >
                {openSidebar ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
              </button>
              <div>
                <div className="text-[11px] uppercase tracking-widest text-muted-foreground">
                  Portail
                </div>
                <div className="font-display text-lg text-foreground">
                  {admin ? "Cabinet ALBARKA" : "Bienvenue"}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="hidden sm:block text-right">
                <div className="text-sm font-medium text-foreground">{user?.full_name}</div>
                {user?.company && (
                  <div className="text-[11px] text-muted-foreground">{user.company}</div>
                )}
              </div>
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-[#0F6B4A] to-[#E5A24B] flex items-center justify-center text-white font-semibold">
                {user?.full_name?.[0] || "?"}
              </div>
            </div>
          </div>
        </header>
        <main className="flex-1 p-5 md:p-8 max-w-7xl w-full mx-auto">
          <Outlet />
        </main>
      </div>
      {/* Chat interne — strictement réservé aux collaborateurs, jamais aux clients */}
      {admin && <ChatBubble />}
      {/* Déconnexion automatique après inactivité (sauf tâche en cours) */}
      <AutoLogoutGate />
      {/* Bulle Paiements — accès rapide à un lien PawaPay, réservée au rôle caissier */}
      {admin && canUsePayments && <PaymentBubble />}
    </div>
  );
}
