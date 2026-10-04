/*
  Page « Sauvegardes » (lot 13.2) — comme sur SAWALI, réservée au compte admin
  du portail (admin@sawalismartsystems.com) ; contrôle aussi côté serveur (403).
  - état : dernière sauvegarde réussie, dernière erreur, prochaine sauvegarde ;
  - réglages : où vont les sauvegardes (bucket, dossier) — jamais de secret ;
  - bouton « Sauvegarder maintenant » (toast « Patientez… » + jauge) ;
  - liste des sauvegardes présentes dans R2 et journal des 20 dernières tentatives ;
  - encadré « Transmission WhatsApp » (lot 13.8) : canal WhatsApp utilisé
    (WABA propre ou Transmission WA Universelle Liluvine) et envoi d'un test.
*/
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Clock, DatabaseBackup, Loader2, MessageCircle, RefreshCw, Send } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient, extractError } from "@/lib/api";
import MentionVersion from "@/components/MentionVersion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

// Même compte que ADMIN_ACCOUNT_EMAIL côté serveur (albarka_models.py)
const ADMIN_ACCOUNT_EMAIL = "admin@sawalismartsystems.com";

// Date/heure lisible en français (heure locale du poste)
const fmtDateTime = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR") : "—");

// Taille lisible : octets -> Ko / Mo
const fmtTaille = (n) => {
  if (n == null) return "—";
  if (n < 1024) return `${n} o`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} Ko`;
  return `${(n / 1024 / 1024).toFixed(2)} Mo`;
};

export default function AdminSauvegardes() {
  const { user } = useAuth();
  const isSuperAdmin = (user?.email || "").toLowerCase() === ADMIN_ACCOUNT_EMAIL;

  // Toute autre personne voit un simple message (le serveur refuse aussi)
  if (!isSuperAdmin) {
    return (
      <div className="albarka-card p-10 text-center text-muted-foreground" data-testid="sauvegardes-forbidden">
        Cette page est réservée à l'administrateur du portail.
      </div>
    );
  }
  return <PageSauvegardes />;
}

function PageSauvegardes() {
  const [etat, setEtat] = useState(null);       // réponse de GET /_admin/sauvegardes
  const [chargement, setChargement] = useState(true);
  const [enCours, setEnCours] = useState(false); // sauvegarde manuelle en cours
  const [selection, setSelection] = useState(null); // ligne sélectionnée (règle 3)

  // Chargement de l'état complet
  const charger = useCallback(async () => {
    setChargement(true);
    try {
      const { data } = await apiClient.get("/_admin/sauvegardes");
      setEtat(data);
    } catch (e) {
      toast.error(extractError(e));
    } finally {
      setChargement(false);
    }
  }, []);

  useEffect(() => { charger(); }, [charger]);

  // Sauvegarde immédiate : toast « Patientez… » pendant l'opération
  const sauvegarderMaintenant = async () => {
    setEnCours(true);
    const attente = toast.loading("Patientez… sauvegarde de la base en cours");
    try {
      const { data } = await apiClient.post("/_admin/sauvegardes/maintenant");
      toast.success(`Sauvegarde déposée (${fmtTaille(data.taille)})`, { id: attente });
      await charger();
    } catch (e) {
      toast.error(extractError(e), { id: attente });
      await charger();
    } finally {
      setEnCours(false);
    }
  };

  const reglages = etat?.reglages || {};

  return (
    <div className="space-y-6" data-testid="sauvegardes-page">
      {/* En-tête de page */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Administration</div>
          <h1 className="font-display text-3xl md:text-4xl">Sauvegardes</h1>
          {/* Règle du propriétaire : libellé de version COMPLET sur les pages d'administration */}
          <MentionVersion detaille testId="sauvegardes-version" className="block text-xs text-muted-foreground mt-1" />
          <p className="text-muted-foreground mt-1">
            Copie chiffrée de toute la base, chaque nuit à {String(reglages.heure_utc ?? 2).padStart(2, "0")} h UTC,
            dans Cloudflare R2. Les {reglages.conservation ?? 30} dernières sont gardées.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={charger} disabled={chargement} data-testid="sauvegardes-actualiser">
            <RefreshCw className={`h-4 w-4 mr-2 ${chargement ? "animate-spin" : ""}`} /> Actualiser
          </Button>
          <Button onClick={sauvegarderMaintenant} disabled={enCours || !reglages.configuree} data-testid="sauvegardes-maintenant">
            {enCours ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <DatabaseBackup className="h-4 w-4 mr-2" />}
            Sauvegarder maintenant
          </Button>
        </div>
      </div>

      {/* Jauge circulaire pendant le premier chargement */}
      {chargement && !etat && (
        <div className="flex justify-center py-16"><Loader2 className="h-10 w-10 animate-spin text-[#0F6B4A]/60" /></div>
      )}

      {etat && (
        <>
          {/* Configuration manquante : message clair, sans aucun secret */}
          {!reglages.configuree && (
            <div className="albarka-card p-4 border-amber-300 bg-amber-50 text-amber-900 flex gap-3" data-testid="sauvegardes-non-configurees">
              <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
              <div className="text-sm">
                Sauvegardes non configurées. Dans Render (albarka-backend → Environment), saisir les mêmes valeurs que
                SAWALI : <code>SAUVEGARDE_AUTO_PHRASE</code>, <code>R2_SAUVEGARDES_ACCOUNT_ID</code>,{" "}
                <code>R2_SAUVEGARDES_ACCESS_KEY_ID</code>, <code>R2_SAUVEGARDES_SECRET_ACCESS_KEY</code>.
              </div>
            </div>
          )}

          {/* Trois cartes d'état */}
          <div className="grid gap-4 md:grid-cols-3">
            <div className="albarka-card p-5" data-testid="sauvegardes-derniere">
              <div className="flex items-center gap-2 text-sm text-muted-foreground"><CheckCircle2 className="h-4 w-4 text-[#0F6B4A]" /> Dernière sauvegarde réussie</div>
              <div className="mt-2 text-xl font-semibold">{fmtDateTime(etat.derniere_reussie?.date)}</div>
              <div className="text-xs text-muted-foreground mt-1">
                {etat.derniere_reussie ? `${fmtTaille(etat.derniere_reussie.taille)} · ${etat.derniere_reussie.origine || "automatique"}` : "Aucune pour l'instant"}
              </div>
            </div>
            <div className="albarka-card p-5" data-testid="sauvegardes-prochaine">
              <div className="flex items-center gap-2 text-sm text-muted-foreground"><Clock className="h-4 w-4" /> Prochaine sauvegarde automatique</div>
              <div className="mt-2 text-xl font-semibold">{reglages.automatique ? fmtDateTime(etat.prochaine) : "Désactivée"}</div>
              <div className="text-xs text-muted-foreground mt-1">Heure de votre poste</div>
            </div>
            <div className="albarka-card p-5" data-testid="sauvegardes-erreur">
              <div className="flex items-center gap-2 text-sm text-muted-foreground"><AlertTriangle className="h-4 w-4 text-amber-600" /> Dernière erreur</div>
              <div className="mt-2 text-xl font-semibold">{fmtDateTime(etat.derniere_erreur?.date)}</div>
              <div className="text-xs text-muted-foreground mt-1 break-words">{etat.derniere_erreur?.erreur || "Aucune"}</div>
            </div>
          </div>

          {/* Réglages (noms seulement, jamais de valeur secrète) */}
          <div className="albarka-card p-5 text-sm grid gap-1 md:grid-cols-2" data-testid="sauvegardes-reglages">
            <div><span className="text-muted-foreground">Destination : </span>{reglages.source || "non configurée"}</div>
            <div><span className="text-muted-foreground">Bucket : </span>{reglages.bucket || "—"}</div>
            <div><span className="text-muted-foreground">Dossier : </span>{reglages.prefixe}</div>
            <div><span className="text-muted-foreground">Chiffrement : </span>{reglages.phrase ? `phrase ${reglages.phrase}` : "phrase absente"}</div>
          </div>

          {/* Lot 13.8 — Transmission WhatsApp (WABA propre ou Liluvine) */}
          <EncadreTransmissionWa />

          {/* Sauvegardes présentes dans R2 */}
          <div className="albarka-card p-0 overflow-hidden">
            <div className="px-5 py-3 border-b font-medium">Sauvegardes conservées ({etat.sauvegardes.length})</div>
            {etat.erreur_liste && <div className="px-5 py-3 text-sm text-amber-800 bg-amber-50">{etat.erreur_liste}</div>}
            <Table data-testid="sauvegardes-liste">
              <TableHeader>
                <TableRow><TableHead>Fichier</TableHead><TableHead>Date</TableHead><TableHead className="text-right">Taille</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {etat.sauvegardes.map((o) => (
                  <TableRow key={o.cle} onClick={() => setSelection(o.cle)}
                            aria-selected={selection === o.cle ? "true" : "false"} className="cursor-pointer">
                    <TableCell className="font-mono text-xs">{o.cle.split("/").pop()}</TableCell>
                    <TableCell>{fmtDateTime(o.date)}</TableCell>
                    <TableCell className="text-right">{fmtTaille(o.taille)}</TableCell>
                  </TableRow>
                ))}
                {etat.sauvegardes.length === 0 && (
                  <TableRow><TableCell colSpan={3} className="text-center text-muted-foreground py-6">Aucune sauvegarde dans R2.</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          {/* Journal des dernières tentatives (automatiques et manuelles) */}
          <div className="albarka-card p-0 overflow-hidden">
            <div className="px-5 py-3 border-b font-medium">Journal</div>
            <Table data-testid="sauvegardes-journal">
              <TableHeader>
                <TableRow><TableHead>Date</TableHead><TableHead>Statut</TableHead><TableHead>Origine</TableHead><TableHead>Détail</TableHead></TableRow>
              </TableHeader>
              <TableBody>
                {etat.journal.map((j, i) => (
                  <TableRow key={`${j.date}-${i}`}>
                    <TableCell>{fmtDateTime(j.date)}</TableCell>
                    <TableCell>
                      {j.statut === "ok"
                        ? <Badge className="bg-emerald-100 text-emerald-800 hover:bg-emerald-100">Réussie</Badge>
                        : <Badge className="bg-red-100 text-red-800 hover:bg-red-100">Échec</Badge>}
                    </TableCell>
                    <TableCell>{j.origine || "automatique"}{j.par ? ` (${j.par})` : ""}</TableCell>
                    <TableCell className="text-xs break-words">{j.statut === "ok" ? `${j.cle?.split("/").pop()} · ${fmtTaille(j.taille)}` : j.erreur}</TableCell>
                  </TableRow>
                ))}
                {etat.journal.length === 0 && (
                  <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground py-6">Aucune tentative pour l'instant.</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </div>
  );
}

/*
  Encadré « Transmission WhatsApp » (lot 13.8).
  Règle du propriétaire : ALBARKA envoie ses WhatsApp avec ses propres
  paramètres WABA s'ils sont configurés ; sinon par la Transmission WA
  Universelle Liluvine (SAWALI). Affiche l'état des deux canaux (jamais la clé)
  et permet d'envoyer un message de test à un numéro.
*/
function EncadreTransmissionWa() {
  const [etat, setEtat] = useState(null);      // réponse de GET /_admin/transmission-wa/etat
  const [numero, setNumero] = useState("");    // numéro saisi pour le test
  const [envoi, setEnvoi] = useState(false);   // test en cours

  // Lecture de l'état des canaux
  const chargerEtat = useCallback(async () => {
    try {
      const { data } = await apiClient.get("/_admin/transmission-wa/etat");
      setEtat(data);
    } catch (e) {
      toast.error(extractError(e));
    }
  }, []);

  useEffect(() => { chargerEtat(); }, [chargerEtat]);

  // Envoi du message de test : toast « Patientez… » pendant l'appel
  const envoyerTest = async () => {
    const n = numero.replace(/\s+/g, "");
    if (!n.startsWith("+")) {
      toast.error("Numéro attendu au format international (+226…)");
      return;
    }
    setEnvoi(true);
    const attente = toast.loading("Patientez… envoi du message de test");
    try {
      const { data } = await apiClient.post("/_admin/transmission-wa/test", { numero: n });
      const canal = data.canal === "waba" ? "WABA ALBARKA" : data.canal === "liluvine" ? "Transmission Liluvine" : "aucun canal";
      if (data.ok) toast.success(`Message de test envoyé (${canal})`, { id: attente });
      else toast.error(`Échec (${canal}) : ${data.erreur || "erreur inconnue"}`, { id: attente });
    } catch (e) {
      toast.error(extractError(e), { id: attente });
    } finally {
      setEnvoi(false);
    }
  };

  // Canal effectivement utilisé selon la règle (WABA prioritaire)
  const canalActif = !etat ? "…" : etat.waba_configure ? "WABA propre d'ALBARKA"
    : etat.liluvine_configure ? "Transmission WA Universelle Liluvine (SAWALI)" : "aucun (WhatsApp indisponible)";

  return (
    <div className="albarka-card p-5 space-y-3" data-testid="transmission-wa">
      <div className="flex items-center gap-2 font-medium"><MessageCircle className="h-4 w-4 text-[#0F6B4A]" /> Transmission WhatsApp</div>
      <div className="text-sm grid gap-1 md:grid-cols-3">
        <div><span className="text-muted-foreground">WABA propre : </span>{etat ? (etat.waba_configure ? "configuré" : "non configuré") : "…"}</div>
        <div><span className="text-muted-foreground">Transmission Liluvine : </span>{etat ? (etat.liluvine_configure ? "configurée" : "non configurée") : "…"}</div>
        <div><span className="text-muted-foreground">Émetteur : </span>{etat?.emetteur || "—"}</div>
      </div>
      <div className="text-sm"><span className="text-muted-foreground">Canal utilisé : </span><strong data-testid="transmission-wa-canal">{canalActif}</strong></div>
      {/* Champ numéro + bouton de test */}
      <div className="flex flex-wrap gap-2 items-center">
        <Input value={numero} onChange={(e) => setNumero(e.target.value)} placeholder="+226 70 00 00 00"
               className="max-w-xs" data-testid="transmission-wa-numero" />
        <Button onClick={envoyerTest} disabled={envoi || !numero.trim()} data-testid="transmission-wa-tester">
          {envoi ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Send className="h-4 w-4 mr-2" />}
          Envoyer un test
        </Button>
      </div>
    </div>
  );
}
