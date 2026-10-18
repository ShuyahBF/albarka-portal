/*
  InstallerApplication — bouton « Installer l'application » (Android, PWABuilder / TWA).
  - Chrome propose l'installation par l'événement « beforeinstallprompt » : il est capté au démarrage
    (src/index.js, window.__albarkaInvite) et offert ici sur un bouton.
  - Si le navigateur ne le propose pas (iPhone, Firefox, déjà refusé…), le bouton ouvre une petite fenêtre
    qui explique les gestes à faire.
  - Rien n'est affiché quand l'application est déjà installée (mode plein écran).
*/
import React, { useEffect, useState } from "react";
import { Download, Smartphone } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";

// L'application tourne-t-elle déjà « installée » (plein écran, sans barre d'adresse) ?
const dejaInstallee = () =>
  window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true;

export default function InstallerApplication({ className = "", sombre = false, testId = "installer-application" }) {
  const [invite, setInvite] = useState(() => window.__albarkaInvite || null);
  const [installee, setInstallee] = useState(dejaInstallee);
  const [aide, setAide] = useState(false);

  useEffect(() => {
    // L'invitation peut arriver après l'affichage de la page
    const surInvite = () => setInvite(window.__albarkaInvite || null);
    const surInstallation = () => { window.__albarkaInvite = null; setInvite(null); setInstallee(true); };
    window.addEventListener("albarka-invite", surInvite);
    window.addEventListener("appinstalled", surInstallation);
    return () => {
      window.removeEventListener("albarka-invite", surInvite);
      window.removeEventListener("appinstalled", surInstallation);
    };
  }, []);

  if (installee) return null;

  // Clic : installation directe si Chrome la propose, sinon explication des gestes
  const cliquer = async () => {
    if (!invite) { setAide(true); return; }
    invite.prompt();
    try { await invite.userChoice; } catch { /* choix ignoré */ }
    window.__albarkaInvite = null;
    setInvite(null);
  };

  const estIphone = /iphone|ipad|ipod/i.test(navigator.userAgent);

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={cliquer}
        className={`${sombre ? "border-white/20 text-white bg-transparent hover:bg-white/10 hover:text-[#E5A24B]" : "border-[#0F6B4A]/40 text-[#0F6B4A] hover:bg-[#0F6B4A]/5"} ${className}`}
        data-testid={testId}
      >
        <Download className="w-4 h-4 mr-2" />
        Installer l'application
      </Button>

      {/* Fenêtre d'aide : 28 rem au plus, 85 % de la hauteur, défilement dans la fenêtre */}
      <Dialog open={aide} onOpenChange={setAide}>
        <DialogContent className="max-w-md max-h-[85dvh] overflow-y-auto w-[calc(100%-2rem)]" data-testid={`${testId}-aide`}>
          <DialogHeader>
            <DialogTitle><Smartphone className="w-5 h-5 text-[#0F6B4A]" /> Installer ALBARKA</DialogTitle>
            <DialogDescription>
              Le portail s'ouvre alors en plein écran, depuis une icône de votre écran d'accueil.
            </DialogDescription>
          </DialogHeader>
          {estIphone ? (
            <ol className="list-decimal space-y-1.5 pl-5 text-sm">
              <li>Ouvrez ce site dans <b>Safari</b>.</li>
              <li>Touchez le bouton <b>Partager</b> (carré avec une flèche vers le haut).</li>
              <li>Choisissez <b>Sur l'écran d'accueil</b>.</li>
            </ol>
          ) : (
            <>
              <p className="text-sm">Sur Android, avec <b>Chrome</b> :</p>
              <ol className="list-decimal space-y-1.5 pl-5 text-sm">
                <li>Touchez le menu <b>⋮</b> en haut à droite.</li>
                <li>Choisissez <b>Installer l'application</b> (ou <b>Ajouter à l'écran d'accueil</b>).</li>
                <li>Confirmez : l'icône ALBARKA apparaît sur votre écran d'accueil.</li>
              </ol>
              <p className="text-xs text-muted-foreground">
                Le bouton d'installation direct n'apparaît que dans Chrome, quand le site est ouvert depuis une adresse sécurisée.
              </p>
            </>
          )}
          <Button type="button" onClick={() => setAide(false)} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white">Compris</Button>
        </DialogContent>
      </Dialog>
    </>
  );
}
