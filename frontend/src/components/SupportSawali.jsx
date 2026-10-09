/*
  SupportSawali — pictogramme « Assistance » + fenêtre de discussion avec le support SAWALI (lot 23).

  Demande du propriétaire (09/10/2026), comme sur bfmobility : un petit pictogramme d'assistance (casque) dans
  l'en-tête du portail, visible à tout moment une fois connecté (personnel du cabinet ET espace client).
  Un clic ouvre une petite fenêtre de discussion :
    - les messages partent vers le serveur ALBARKA (/api/support-sawali/…), qui les relaie à SAWALI par une
      requête signée (aucun secret dans le navigateur) ;
    - fenêtre ouverte : les réponses du support sont relues toutes les 5 s ;
    - fenêtre fermée : vérification des réponses non lues toutes les 60 s (pastille rouge) ;
    - un SON est joué à chaque nouvelle réponse du support ;
    - la requête est numérotée par SAWALI (SUP-…) et son état est affiché (en attente, en cours, terminée).
  Le pictogramme reste caché si ALBARKA n'est pas relié à SAWALI (clé LILUVINE_WA_HMAC absente).
*/
import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Headset, Loader2, Send, X } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { BarrePictos, PieceJointe } from "./SupportPictos";   // lot 24 (SAWALI lot 93) : emojis, photo, trombone, note vocale

const RAFRAICHIR_OUVERT_MS = 5000;     // lecture du fil, fenêtre ouverte
const RAFRAICHIR_FERME_MS = 60000;     // vérification des réponses non lues, fenêtre fermée

// --- Son de notification (3 notes montantes, comme le chat de SAWALI) ; le navigateur l'autorise après un clic
let contexteAudio = null;
function jouerSon() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    contexteAudio = contexteAudio || new Ctx();
    if (contexteAudio.state === "suspended") contexteAudio.resume().catch(() => {});
    const t0 = contexteAudio.currentTime + 0.02;
    [[659.25, 0, 0.18], [783.99, 0.14, 0.18], [1046.5, 0.28, 0.32]].forEach(([f, debut, duree]) => {
      const osc = contexteAudio.createOscillator();
      const env = contexteAudio.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(f, t0 + debut);
      env.gain.setValueAtTime(0.0001, t0 + debut);
      env.gain.exponentialRampToValueAtTime(0.5, t0 + debut + 0.02);
      env.gain.exponentialRampToValueAtTime(0.0001, t0 + debut + duree);
      osc.connect(env);
      env.connect(contexteAudio.destination);
      osc.start(t0 + debut);
      osc.stop(t0 + debut + duree + 0.02);
    });
  } catch {
    /* son impossible : sans importance */
  }
}

// Heure courte « 14:05 » à partir d'une date ISO
const heure = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
};

// Libellé de l'état de la requête (numéro SUP-… donné par SAWALI)
const ETATS = { attente: "⏳ En attente du support", active: "💬 En cours", terminee: "✅ Terminée" };

export default function SupportSawali() {
  const [actif, setActif] = useState(false);          // ALBARKA relié à SAWALI ?
  const [ouvert, setOuvert] = useState(false);        // fenêtre de discussion affichée ?
  const [messages, setMessages] = useState([]);
  const [requete, setRequete] = useState(null);
  const [nonLus, setNonLus] = useState(0);
  const [texte, setTexte] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState("");
  const dernierRef = useRef("");                      // date du dernier message reçu (lecture incrémentale)
  const nonLusRef = useRef(0);
  const filRef = useRef(null);

  // Au chargement : le pictogramme n'apparaît que si la clé est configurée côté serveur
  useEffect(() => {
    apiClient.get("/support-sawali/etat").then(({ data }) => setActif(!!data?.actif)).catch(() => setActif(false));
  }, []);

  // Lecture du fil (fenêtre ouverte) : nouveaux messages ajoutés à la suite, réponses marquées lues
  const lireFil = useCallback(async () => {
    try {
      const { data } = await apiClient.post("/support-sawali/fil", { depuis: dernierRef.current || null, marquer_lu: true });
      const nouveaux = data?.messages || [];
      if (nouveaux.length) {
        // Son seulement pour une réponse du support arrivée après le premier chargement
        if (dernierRef.current && nouveaux.some((m) => m.de === "support")) jouerSon();
        dernierRef.current = nouveaux[nouveaux.length - 1].le;
        setMessages((avant) => {
          const connus = new Set(avant.map((m) => m.id));
          return [...avant, ...nouveaux.filter((m) => !connus.has(m.id))];
        });
      }
      setRequete(data?.requete || null);
      setNonLus(0);
      nonLusRef.current = 0;
      setErreur("");
    } catch (e) {
      setErreur(extractError(e, "Support SAWALI injoignable : réessayez dans un instant."));
    }
  }, []);

  // Fenêtre fermée : simple vérification des réponses non lues (son si leur nombre augmente)
  const verifierNonLus = useCallback(async () => {
    try {
      const { data } = await apiClient.post("/support-sawali/fil", { depuis: dernierRef.current || null, marquer_lu: false });
      const n = data?.non_lus || 0;
      if (n > nonLusRef.current) jouerSon();
      nonLusRef.current = n;
      setNonLus(n);
    } catch {
      /* silencieux : nouvel essai à la prochaine vérification */
    }
  }, []);

  // Minuterie : toutes les 5 s fenêtre ouverte, toutes les 60 s fenêtre fermée
  useEffect(() => {
    if (!actif) return undefined;
    const action = ouvert ? lireFil : verifierNonLus;
    action();
    const minuterie = setInterval(action, ouvert ? RAFRAICHIR_OUVERT_MS : RAFRAICHIR_FERME_MS);
    return () => clearInterval(minuterie);
  }, [actif, ouvert, lireFil, verifierNonLus]);

  // Défilement automatique vers le dernier message
  useEffect(() => {
    if (filRef.current) filRef.current.scrollTop = filRef.current.scrollHeight;
  }, [messages, ouvert]);

  // Envoi d'un message (bouton « Patientez… » avec jauge qui tourne pendant l'envoi)
  const envoyer = async (e) => {
    e.preventDefault();
    const t = texte.trim();
    if (!t || envoi) return;
    setEnvoi(true);
    try {
      const { data } = await apiClient.post("/support-sawali/messages", { texte: t });
      setTexte("");
      if (data?.requete) setRequete(data.requete);
      await lireFil();
    } catch (err) {
      setErreur(extractError(err, "Envoi impossible : votre message est conservé, réessayez."));
    } finally {
      setEnvoi(false);
    }
  };

  // Clé absente côté serveur : rien n'est affiché
  if (!actif) return null;

  return (
    <>
      {/* Pictogramme discret (casque d'assistance) + pastille rouge des réponses non lues */}
      <button
        type="button"
        onClick={() => setOuvert((v) => !v)}
        title="Assistance — écrire au support SAWALI"
        aria-label="Assistance — écrire au support SAWALI"
        aria-expanded={ouvert}
        data-testid="support-sawali-btn"
        className={`relative w-10 h-10 rounded-full flex items-center justify-center transition-colors ${
          ouvert ? "bg-[#0F6B4A] text-white" : "text-[#0F6B4A] hover:bg-[#0F6B4A]/10"
        }`}
      >
        <Headset className="w-5 h-5" />
        {nonLus > 0 && (
          <span
            className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-semibold flex items-center justify-center"
            data-testid="support-sawali-non-lus"
          >
            {nonLus > 99 ? "99+" : nonLus}
          </span>
        )}
      </button>

      {/* Fenêtre de discussion : sous l'en-tête à droite (ne cache pas la bulle du chat interne) ;
          presque plein écran sur téléphone. Rendue directement dans <body> (createPortal) : l'en-tête du portail
          est flouté (backdrop-blur), ce qui enfermerait une fenêtre « fixed » dans l'en-tête. */}
      {ouvert && createPortal(
        <div
          role="dialog"
          aria-label="Support SAWALI"
          data-testid="support-sawali-fenetre"
          className="fixed inset-x-2 top-16 bottom-2 z-[60] flex flex-col overflow-hidden rounded-xl bg-white text-foreground shadow-2xl border border-[hsl(var(--border))] sm:inset-x-auto sm:bottom-auto sm:right-6 sm:top-20 sm:w-[360px] sm:h-[70vh] sm:max-h-[560px]"
        >
          {/* Bandeau de la fenêtre : couleurs de la barre latérale ALBARKA */}
          <div className="flex items-center gap-2 bg-[#0B1912] px-4 py-3 text-white">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#0F6B4A] to-[#E5A24B] flex items-center justify-center shrink-0">
              <Headset className="w-4 h-4 text-white" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="font-display text-sm leading-tight">Support SAWALI</p>
              <p className="truncate text-[11px] text-white/60">
                {requete
                  ? `${requete.numero} · ${ETATS[requete.statut] || requete.libelle || ""}`
                  : "Posez votre question, nous vous répondons ici."}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setOuvert(false)}
              className="p-1.5 rounded-lg hover:bg-white/10 hover:text-[#E5A24B]"
              aria-label="Fermer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Fil de la discussion : mes messages à droite (vert ALBARKA), réponses du support à gauche */}
          <div ref={filRef} className="flex-1 space-y-2 overflow-y-auto bg-slate-50 p-3">
            {messages.length === 0 && (
              <p className="py-6 text-center text-sm italic text-muted-foreground">Aucun message pour l'instant.</p>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`flex ${m.de === "moi" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm shadow-sm ${
                    m.systeme
                      ? "bg-amber-50 text-amber-900 border border-amber-200"
                      : m.de === "moi"
                        ? "bg-[#0F6B4A] text-white"
                        : "bg-white border border-[hsl(var(--border))]"
                  }`}
                >
                  {m.de !== "moi" && !m.systeme && (
                    <p className="mb-0.5 text-[11px] font-semibold text-[#0F6B4A]">{m.auteur}</p>
                  )}
                  {/* Lot 24 : photo, document ou vidéo joint au message */}
                  {m.media && <div className="mb-1"><PieceJointe api={apiClient} media={m.media} moi={m.de === "moi"} /></div>}
                  {m.texte && <p className="whitespace-pre-wrap break-words">{m.texte}</p>}
                  <p className={`mt-1 text-right text-[10px] ${m.de === "moi" ? "text-white/60" : "text-muted-foreground"}`}>
                    {heure(m.le)}
                  </p>
                </div>
              </div>
            ))}
          </div>

          {/* Message d'erreur lisible (support non activé, injoignable…) */}
          {erreur && <p className="bg-red-50 px-3 py-1.5 text-xs text-red-700" data-testid="support-sawali-erreur">{erreur}</p>}

          {/* Zone de saisie : Entrée envoie, Maj+Entrée passe à la ligne */}
          {/* Lot 24 : pictogrammes comme dans le chat SAWALI (emojis, photo, trombone, note vocale) */}
          <BarrePictos api={apiClient} texte={texte} setTexte={setTexte} desactive={envoi} onEnvoye={lireFil} onErreur={setErreur} />
          <form onSubmit={envoyer} className="flex gap-2 p-2">
            <textarea
              value={texte}
              onChange={(e) => setTexte(e.target.value)}
              rows={2}
              maxLength={2000}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) envoyer(e);
              }}
              placeholder="Votre message…"
              className="min-w-0 flex-1 resize-none rounded-lg border border-[hsl(var(--border))] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#0F6B4A]/40"
              data-testid="support-sawali-saisie"
            />
            <button
              type="submit"
              disabled={envoi || !texte.trim()}
              className="rounded-lg bg-[#0F6B4A] px-3 text-sm font-semibold text-white hover:bg-[#0A4E36] disabled:opacity-40 flex items-center gap-1.5"
              data-testid="support-sawali-envoyer"
            >
              {envoi ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              {envoi ? "Patientez…" : "Envoyer"}
            </button>
          </form>
        </div>,
        document.body
      )}
    </>
  );
}
