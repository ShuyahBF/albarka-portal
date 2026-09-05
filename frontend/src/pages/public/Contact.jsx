import React, { useEffect, useState } from "react";
import PublicLayout from "@/components/PublicLayout";
import { MapPin, Phone, Mail, MessageCircle } from "lucide-react";
import { API } from "@/lib/api";

export default function Contact() {
  const [wa, setWa] = useState({ number: "", message: "" });
  useEffect(() => {
    fetch(`${API}/public/whatsapp-contact`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setWa(d))
      .catch(() => {});
  }, []);
  const cleanNumber = wa.number ? wa.number.replace(/[^\d]/g, "") : "";
  const waUrl = cleanNumber
    ? `https://wa.me/${cleanNumber}?text=${encodeURIComponent(wa.message || "")}`
    : null;

  return (
    <PublicLayout>
      <section className="py-16 bg-[var(--albarka-paper)]">
        <div className="max-w-4xl mx-auto px-6">
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-3">
            Contact
          </div>
          <h1 className="font-display text-4xl md:text-5xl text-foreground mb-8">
            Parlons de votre <span className="albarka-underline">projet</span>.
          </h1>
          <div className="grid md:grid-cols-3 gap-4 mt-10">
            <div className="albarka-card p-6" data-testid="contact-address">
              <MapPin className="w-6 h-6 text-[#0F6B4A] mb-3" />
              <div className="font-medium mb-1">Adresse</div>
              <div className="text-sm text-muted-foreground">
                Ouagadougou, Burkina Faso
              </div>
            </div>
            <div className="albarka-card p-6" data-testid="contact-phone">
              <Phone className="w-6 h-6 text-[#0F6B4A] mb-3" />
              <div className="font-medium mb-1">Téléphone / WhatsApp</div>
              {waUrl ? (
                <a
                  href={waUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-2 text-sm text-[#0F6B4A] hover:text-[#25D366] font-medium underline underline-offset-2"
                  data-testid="contact-whatsapp-link"
                >
                  <MessageCircle className="w-4 h-4" />
                  {wa.number}
                </a>
              ) : (
                <div className="text-sm text-muted-foreground">+226 25 00 00 00</div>
              )}
            </div>
            <div className="albarka-card p-6" data-testid="contact-email">
              <Mail className="w-6 h-6 text-[#0F6B4A] mb-3" />
              <div className="font-medium mb-1">Email</div>
              <div className="text-sm text-muted-foreground">contact@albarka-bf.com</div>
            </div>
          </div>
        </div>
      </section>
    </PublicLayout>
  );
}
