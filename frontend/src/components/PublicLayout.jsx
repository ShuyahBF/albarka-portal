import React from "react";
import { Link, useLocation } from "react-router-dom";
import { Sprout, Menu, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import PublicWhatsAppFAB from "@/components/PublicWhatsAppFAB";

const NAV = [
  { to: "/", label: "Accueil" },
  { to: "/missions", label: "Missions" },
  { to: "/services", label: "Services" },
  { to: "/contact", label: "Contact" },
];

export default function PublicLayout({ children }) {
  const [open, setOpen] = React.useState(false);
  const location = useLocation();

  return (
    <div className="min-h-screen flex flex-col bg-[var(--albarka-paper)]">
      <header
        className="sticky top-0 z-50 backdrop-blur-lg bg-[#0B1912]/90 border-b border-white/10"
        data-testid="public-header"
      >
        <div className="max-w-7xl mx-auto flex items-center justify-between px-6 py-4">
          <Link to="/" className="flex items-center gap-2.5" data-testid="public-logo">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-[#0F6B4A] to-[#E5A24B] flex items-center justify-center">
              <Sprout className="w-5 h-5 text-white" />
            </div>
            <span className="font-display text-xl font-semibold tracking-tight text-white">
              ALBARKA
            </span>
          </Link>
          <nav className="hidden md:flex items-center gap-1">
            {NAV.map((n) => (
              <Link
                key={n.to}
                to={n.to}
                data-testid={`nav-${n.label.toLowerCase()}`}
                className={`px-4 py-2 rounded-lg text-sm transition-colors ${
                  location.pathname === n.to
                    ? "text-[#E5A24B]"
                    : "text-white/70 hover:text-white hover:bg-white/5"
                }`}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="hidden md:flex items-center gap-3">
            <Link to="/login">
              <Button
                variant="outline"
                size="sm"
                className="border-white/20 text-white bg-transparent hover:bg-white/10 hover:text-white"
                data-testid="header-login-btn"
              >
                Espace client
              </Button>
            </Link>
          </div>
          <button
            className="md:hidden text-white"
            onClick={() => setOpen((v) => !v)}
            data-testid="mobile-menu-toggle"
            aria-label="Menu"
          >
            {open ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>
        {open && (
          <div className="md:hidden border-t border-white/10 bg-[#0B1912]">
            <nav className="px-6 py-4 flex flex-col gap-2">
              {NAV.map((n) => (
                <Link
                  key={n.to}
                  to={n.to}
                  onClick={() => setOpen(false)}
                  className="text-white/80 py-2 text-sm"
                  data-testid={`mobile-nav-${n.label.toLowerCase()}`}
                >
                  {n.label}
                </Link>
              ))}
              <Link
                to="/login"
                onClick={() => setOpen(false)}
                className="text-[#E5A24B] py-2 text-sm font-medium"
              >
                Espace client →
              </Link>
            </nav>
          </div>
        )}
      </header>

      <main className="flex-1">{children}</main>

      <footer className="bg-[#0B1912] text-white/70 border-t border-white/10">
        <div className="max-w-7xl mx-auto px-6 py-12 grid md:grid-cols-3 gap-8">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#0F6B4A] to-[#E5A24B] flex items-center justify-center">
                <Sprout className="w-4 h-4 text-white" />
              </div>
              <span className="font-display text-lg text-white">ALBARKA</span>
            </div>
            <p className="text-sm max-w-xs">
              Cabinet d'assistance fiscale et comptable au Burkina Faso.
            </p>
          </div>
          <div>
            <div className="text-white text-sm font-semibold mb-3">Contact</div>
            <p className="text-sm">Ouagadougou, Burkina Faso</p>
            <p className="text-sm mt-1">contact@albarka-bf.com</p>
          </div>
          <div>
            <div className="text-white text-sm font-semibold mb-3">Liens</div>
            <ul className="text-sm space-y-2">
              <li><Link to="/missions" className="hover:text-[#E5A24B]">Nos missions</Link></li>
              <li><Link to="/services" className="hover:text-[#E5A24B]">Services</Link></li>
              <li><Link to="/login" className="hover:text-[#E5A24B]">Espace client</Link></li>
            </ul>
          </div>
        </div>
        <div className="border-t border-white/10 text-center py-4 text-xs text-white/50">
          © 2026 Cabinet ALBARKA — Tous droits réservés
        </div>
      </footer>
      {/* Partie 0 — bouton wa.me public (masqué automatiquement si settings.whatsapp_contact_number vide) */}
      <PublicWhatsAppFAB />
    </div>
  );
}
