import React, { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  FileText,
  CalendarClock,
  Briefcase,
  Users,
  UserCog,
  Sprout,
  LogOut,
  Menu,
  X,
  History,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";

const CLIENT_LINKS = [
  { to: "/portal", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/portal/documents", label: "Mes pièces", icon: FileText },
  { to: "/portal/missions", label: "Mes missions", icon: Briefcase },
  { to: "/portal/echeances", label: "Échéances", icon: CalendarClock },
  { to: "/portal/historique", label: "Historique", icon: History },
];

const STAFF_LINKS = [
  { to: "/admin", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/admin/clients", label: "Clients", icon: Users },
  { to: "/admin/staff", label: "Collaborateurs", icon: UserCog },
  { to: "/admin/documents", label: "Pièces", icon: FileText },
  { to: "/admin/missions", label: "Missions", icon: Briefcase },
  { to: "/admin/echeances", label: "Échéances", icon: CalendarClock },
];

export default function PortalLayout({ admin = false }) {
  const { user, logout } = useAuth();
  const [openSidebar, setOpenSidebar] = useState(false);
  const navigate = useNavigate();
  const links = admin ? STAFF_LINKS : CLIENT_LINKS;

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen bg-[var(--albarka-paper)] flex">
      {/* Sidebar */}
      <aside
        data-testid="portal-sidebar"
        className={`fixed md:sticky top-0 z-40 h-screen w-64 bg-[#0B1912] text-white flex-shrink-0 transition-transform md:translate-x-0 ${
          openSidebar ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="px-5 py-6 border-b border-white/10 flex items-center gap-2.5">
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
        <nav className="p-3 space-y-1">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) => `albarka-sidebar-link ${isActive ? "active" : ""}`}
              onClick={() => setOpenSidebar(false)}
              data-testid={`sidebar-link-${link.label.toLowerCase().replace(/\s+/g, "-")}`}
            >
              <link.icon className="w-4 h-4" />
              <span>{link.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-white/10">
          <div className="text-xs text-white/60 mb-2 truncate">{user?.full_name}</div>
          <div className="text-[11px] text-white/40 mb-3 truncate">
            {user?.roles?.join(", ")}
          </div>
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
    </div>
  );
}
