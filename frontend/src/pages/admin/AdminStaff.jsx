import React, { useEffect, useState, useMemo } from "react";
import { toast } from "sonner";
import { Plus, Pencil, FlaskConical, KeyRound, Eye, EyeOff, Loader2, Trash2, MessageCircle } from "lucide-react";
import AccountActions, { AccountDates } from "@/components/AccountActions";
import { usePresence, PresenceLabel } from "@/components/Presence";
import TemporaryAccessButton from "@/components/TemporaryAccessButton";
import { ui } from "@/components/forms-core/ui";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { useAuth } from "@/contexts/AuthContext";

const STAFF_ROLES = [
  { value: "superviseur", label: "Superviseur" },
  { value: "direction", label: "Direction" },
  { value: "dg", label: "Directeur Général" },
  { value: "administrateur", label: "Administrateur" },
  { value: "secretariat", label: "Secrétariat" },
  { value: "fiscaliste", label: "Fiscaliste" },
  { value: "comptable", label: "Comptable" },
  { value: "aide_comptable", label: "Aide-comptable" },
  { value: "rh", label: "RH" },
  { value: "communication", label: "Communication" },
  // Rôle transversal cumulable : accorde le droit de télécharger les pièces
  // client quel que soit le métier principal du collaborateur.
  { value: "telechargement", label: "Téléchargement" },
  // Rôle cumulable : donne accès au menu et au module Formulaires
  // (création, envoi aux clients, réponses, statistiques).
  { value: "formulaires", label: "Formulaires" },
  // Rôle cumulable : seul habilité à encaisser et à délivrer un reçu
  // (ex. une secrétaire avec ce rôle en plus peut encaisser).
  { value: "caissier", label: "Caissier" },
];

const emptyForm = () => ({
  email: "", full_name: "", phone: "", password: "", roles: ["comptable"],
  can_receive_notifications: true, is_active: true,
});

export default function AdminStaff() {
  const { user: me } = useAuth();
  const myRoles = me?.roles || [];
  // Compte admin du portail (doit rester identique à ADMIN_ACCOUNT_EMAIL côté backend)
  const isAdminAccount = (me?.email || "").toLowerCase() === "admin@sawalismartsystems.com";
  // Rôle Administrateur : visible et attribuable par un Administrateur (règle
  // d'origine), le Superviseur (tous les droits) ou le compte admin.
  const isAdmin = myRoles.includes("administrateur") || myRoles.includes("superviseur") || isAdminAccount;
  // Gestion du personnel : Direction, DG, Administrateur, Superviseur (même règle que le serveur)
  const canEdit = isAdmin || myRoles.includes("direction") || myRoles.includes("dg");
  // Superviseur : supprime un compte du personnel, gère les comptes de test.
  const isSuperviseur = myRoles.includes("superviseur");
  // Compte admin du portail : SEUL habilité à cocher / décocher « Superviseur ».
  // Ligne du tableau : compte admin / compte Superviseur (protégés)
  const isAdminAccountRow = (s) => (s.email || "").toLowerCase() === "admin@sawalismartsystems.com";
  const isSupRow = (s) => (s.roles || []).includes("superviseur");
  // Présence en temps réel (rafraîchie toutes les 15 s)
  const presence = usePresence();
  // Accès temporaires : admin ou adresse désignée par admin (GET /access/me)
  const [canIssueTokens, setCanIssueTokens] = useState(false);
  useEffect(() => { apiClient.get("/access/me").then(({ data }) => setCanIssueTokens(!!data.can_issue_tokens)).catch(() => {}); }, []);

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  // Lot 16 — connexion par WhatsApp : comptes ayant un code PIN
  // ({ user_id: { defini_le, defini_par_nom } } ; jamais le PIN ni son hachage)
  const [pins, setPins] = useState({});
  // Fenêtre « Code PIN WhatsApp » : compte visé, envoi WhatsApp, résultat affiché une seule fois
  const [pinCible, setPinCible] = useState(null);
  const [pinEnvoiWa, setPinEnvoiWa] = useState(true);
  const [pinResultat, setPinResultat] = useState(null);
  const [pinVisible, setPinVisible] = useState(true);
  const [pinBusy, setPinBusy] = useState(false);
  // Pictogramme « œil » des champs mot de passe de cette page (voir / masquer)
  const [voirMdp, setVoirMdp] = useState(false);
  const BoutonOeil = () => (
    <button type="button" onClick={() => setVoirMdp((v) => !v)} title={voirMdp ? "Masquer la saisie" : "Afficher la saisie"}
      aria-label={voirMdp ? "Masquer la saisie" : "Afficher la saisie"}
      className="absolute right-2 top-1/2 -translate-y-1/2 h-7 w-7 inline-flex items-center justify-center rounded text-muted-foreground hover:text-[#0F6B4A]">
      {voirMdp ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
    </button>
  );
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null); // null = create mode
  const [form, setForm] = useState(emptyForm());

  // Rôles proposés dans le formulaire : masque "administrateur" pour les non-admins.
  const visibleRoles = useMemo(
    () => (isAdmin ? STAFF_ROLES : STAFF_ROLES.filter((r) => r.value !== "administrateur")),
    [isAdmin],
  );
  // Comptes de test (bouton « Créer comptes de test »)
  const [openTest, setOpenTest] = useState(false);
  const [testForm, setTestForm] = useState({ email: me?.email || "", password: "", client1_whatsapp: "", client2_whatsapp: "" });
  const [testResult, setTestResult] = useState(null);
  const [testBusy, setTestBusy] = useState(false);

  // Table filtrée : masque les comptes administrateurs pour les non-admins.
  const visibleItems = useMemo(
    () => (isAdmin ? items : items.filter((s) => !(s.roles || []).includes("administrateur"))),
    [items, isAdmin],
  );

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await apiClient.get("/clients/staff");
      setItems(data);
      // PIN WhatsApp (lot 16) : réservé aux gestionnaires du personnel
      if (canEdit) {
        try {
          const { data: lp } = await apiClient.get("/staff-pin");
          setPins(Object.fromEntries((lp || []).map((x) => [x.user_id, x])));
        } catch { setPins({}); }
      }
    } catch (err) {
      toast.error(extractError(err));
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const toggleRole = (r) => {
    setForm((f) => ({
      ...f,
      roles: f.roles.includes(r) ? f.roles.filter((x) => x !== r) : [...f.roles, r],
    }));
  };

  const openNew = () => {
    setEditing(null);
    setForm(emptyForm());
    setOpen(true);
  };

  const openEdit = (s) => {
    setEditing(s);
    setForm({
      email: s.email || "",
      full_name: s.full_name || "",
      phone: s.phone || "",
      password: "", // not editable here
      roles: s.roles || [],
      can_receive_notifications: s.can_receive_notifications !== false,
      is_active: s.is_active !== false,
    });
    setOpen(true);
  };

  const submit = async () => {
    if (editing) {
      // Edit mode: PATCH (email + password are read-only here)
      if (!form.full_name || form.roles.length === 0) {
        toast.error("Nom et au moins un rôle requis"); return;
      }
      try {
        await apiClient.patch(`/clients/${editing.id}`, {
          full_name: form.full_name,
          phone: form.phone || null,
          roles: form.roles,
          can_receive_notifications: form.can_receive_notifications,
          is_active: form.is_active,
        });
        toast.success("Personnel mis à jour");
        setOpen(false);
        setEditing(null);
        setForm(emptyForm());
        await load();
      } catch (err) {
        toast.error(extractError(err));
      }
      return;
    }
    // Create mode
    if (!form.email || !form.full_name || !form.password || form.roles.length === 0) {
      toast.error("Champs requis manquants"); return;
    }
    try {
      await apiClient.post("/clients/staff", form);
      toast.success("Personnel créé");
      setOpen(false);
      setForm(emptyForm());
      await load();
    } catch (err) {
      toast.error(extractError(err));
    }
  };

  // --- Lot 16 : code PIN de connexion par WhatsApp --------------------------------
  // Exclus (comme côté serveur) : Superviseur et compte admin du portail.
  const pinPossible = (s) => canEdit && !isSupRow(s) && !isAdminAccountRow(s);
  const ouvrirPin = (s) => {
    setPinCible(s);
    setPinResultat(null);
    setPinVisible(true);
    setPinEnvoiWa(true);
  };
  // Génère (ou remplace) le PIN : affiché une seule fois. Toast « Patientez… » + jauge.
  const genererPin = async () => {
    setPinBusy(true);
    const attente = toast.loading("Patientez… génération du code PIN");
    try {
      const { data } = await apiClient.post(`/staff-pin/${pinCible.id}`, { envoyer_whatsapp: pinEnvoiWa });
      setPinResultat(data);
      if (data.envoye_whatsapp === false) toast.warning("PIN généré, mais l'envoi WhatsApp a échoué : remettez-le en main propre.", { id: attente });
      else toast.success("Code PIN généré", { id: attente });
      await load();
    } catch (err) {
      toast.error(extractError(err), { id: attente });
    } finally { setPinBusy(false); }
  };
  // Retire le PIN : plus de connexion par WhatsApp pour ce collaborateur
  const retirerPin = async () => {
    setPinBusy(true);
    const attente = toast.loading("Patientez…");
    try {
      await apiClient.delete(`/staff-pin/${pinCible.id}`);
      toast.success("Code PIN retiré", { id: attente });
      setPinCible(null);
      await load();
    } catch (err) {
      toast.error(extractError(err), { id: attente });
    } finally { setPinBusy(false); }
  };

  // --- Comptes de test (superviseur) --------------------------------------------
  const createTestAccounts = async () => {
    if (!testForm.email || testForm.password.length < 8) { toast.error("E-mail et mot de passe (8 caractères min.) requis"); return; }
    setTestBusy(true);
    try {
      const { data } = await apiClient.post("/clients/test-accounts", {
        email: testForm.email, password: testForm.password,
        client1_whatsapp: testForm.client1_whatsapp || null, client2_whatsapp: testForm.client2_whatsapp || null,
      });
      setTestResult(data.accounts);
      toast.success("Comptes de test prêts");
      await load();
    } catch (err) { toast.error(extractError(err)); } finally { setTestBusy(false); }
  };
  const deleteTestAccounts = async () => {
    setTestBusy(true);
    try {
      const { data } = await apiClient.delete("/clients/test-accounts");
      toast.success(`${data.deleted} compte(s) de test supprimé(s)`);
      setTestResult(null);
      await load();
    } catch (err) { toast.error(extractError(err)); } finally { setTestBusy(false); }
  };

  return (
    <div className="space-y-6" data-testid="admin-staff-page">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
          <h1 className="font-display text-3xl md:text-4xl text-foreground">Personnels</h1>
          <p className="text-muted-foreground mt-1">Équipe du cabinet et leurs rôles.
            <span className="ml-2 text-emerald-700" data-testid="staff-online-count">· {presence.counts.staff_online} collaborateur(s) en ligne</span></p>
        </div>
        <div className="flex flex-wrap gap-2">
        {/* Comptes de test de la recette : superviseur uniquement */}
        {isSuperviseur && (
          <Button variant="outline" onClick={() => { setTestResult(null); setOpenTest(true); }} data-testid="test-accounts-btn">
            <FlaskConical className="w-4 h-4 mr-2" />Créer comptes de test
          </Button>
        )}
        <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) setEditing(null); }}>
          {canEdit && (
            <DialogTrigger asChild>
              <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="new-staff-btn" onClick={openNew}>
                <Plus className="w-4 h-4 mr-2" />Nouveau personnel
              </Button>
            </DialogTrigger>
          )}
          <DialogContent data-testid="staff-dialog">
            <DialogHeader>
              <DialogTitle>{editing ? "Modifier un personnel" : "Nouveau personnel"}</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div>
                <Label>Email {editing && <span className="text-[10px] text-muted-foreground">(non modifiable)</span>}</Label>
                <Input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  readOnly={!!editing}
                  data-testid="staff-email-input"
                />
              </div>
              <div><Label>Nom complet</Label><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} data-testid="staff-name-input" /></div>
              <div><Label>Téléphone</Label><Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="staff-phone-input" /></div>
              {!editing && (
                <div><Label>Mot de passe</Label><div className="relative"><Input type={voirMdp ? "text" : "password"} className="pr-10" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="staff-password-input" /><BoutonOeil /></div></div>
              )}
              <div>
                <Label>Rôles</Label>
                <div className="grid grid-cols-2 gap-2 mt-2">
                  {visibleRoles.map((r) => (
                    <label key={r.value} className="flex items-center gap-2 text-sm cursor-pointer">
                      <Checkbox
                        checked={form.roles.includes(r.value)}
                        onCheckedChange={() => toggleRole(r.value)}
                        // Superviseur : case verrouillée sauf pour le compte admin du portail
                        disabled={r.value === "superviseur" && !isAdminAccount}
                        data-testid={`role-${r.value}`}
                      />
                      {r.label}
                    </label>
                  ))}
                </div>
                {/* Rappel : le rôle Superviseur n'est attribuable que par le compte admin */}
                {!isAdminAccount && <p className="text-[11px] text-muted-foreground mt-2">Le rôle Superviseur ne peut être donné ou retiré que par le compte admin du portail.</p>}
              </div>
              <label className="flex items-center gap-2 text-sm cursor-pointer pt-1">
                <Checkbox
                  checked={form.can_receive_notifications}
                  onCheckedChange={(v) => setForm({ ...form, can_receive_notifications: !!v })}
                  data-testid="staff-notif-checkbox"
                />
                <span>Autoriser la réception des notifications (dépôts, échéances, rapports…)</span>
              </label>
              {editing && (
                <label className="flex items-center gap-2 text-sm cursor-pointer pt-1">
                  <Checkbox
                    checked={form.is_active}
                    onCheckedChange={(v) => setForm({ ...form, is_active: !!v })}
                    data-testid="staff-active-checkbox"
                  />
                  <span>Compte actif</span>
                </label>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
              <Button onClick={submit} className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" data-testid="staff-submit-btn">
                {editing ? "Enregistrer" : "Créer"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        </div>
      </div>

      <div className="albarka-card overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nom</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Rôles</TableHead>
              <TableHead>Téléphone</TableHead>
              <TableHead>Statut</TableHead>
              {canEdit && <TableHead>Connexion WhatsApp</TableHead>}
              <TableHead>Connexion / modification</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={canEdit ? 8 : 7} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && visibleItems.length === 0 && <TableRow><TableCell colSpan={canEdit ? 8 : 7} className="text-center py-10 text-muted-foreground">Aucun personnel.</TableCell></TableRow>}
            {visibleItems.map((s) => (
              <TableRow key={s.id} className="hover:bg-[#0F6B4A]/5">
                <TableCell className="font-medium">
                  {s.full_name}
                  {/* Compte de test : visible du superviseur uniquement */}
                  {s.is_test_account && <span className="ml-2 albarka-chip text-[10px] bg-amber-100 text-amber-800" data-testid={`test-badge-${s.id}`}>TEST</span>}
                </TableCell>
                <TableCell className="text-sm">{s.email}</TableCell>
                <TableCell className="text-xs">
                  <div className="flex flex-wrap gap-1">
                    {s.roles?.map((r) => (
                      <span key={r} className="albarka-chip bg-[#0F6B4A]/10 text-[#0F6B4A]">{r}</span>
                    ))}
                  </div>
                </TableCell>
                <TableCell className="text-sm">{s.phone || "—"}</TableCell>
                <TableCell>
                  {s.is_active === false
                    ? <span className="albarka-chip bg-slate-100 text-slate-500">Inactif</span>
                    : <span className="albarka-chip bg-emerald-100 text-emerald-800">Actif</span>}
                </TableCell>
                {/* Lot 16 : état du code PIN de connexion par WhatsApp */}
                {canEdit && (
                  <TableCell className="text-xs" data-testid={`pin-state-${s.id}`}>
                    {!pinPossible(s)
                      ? <span className="text-muted-foreground">E-mail uniquement</span>
                      : pins[s.id]
                        ? <span className="albarka-chip bg-emerald-100 text-emerald-800">PIN actif</span>
                        : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                )}
                <TableCell>
                  <PresenceLabel presence={presence.items[s.id]} />
                  <AccountDates account={s} />
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  {/* Lot 16 : code PIN de connexion par WhatsApp */}
                  {pinPossible(s) && (
                    <button type="button" onClick={() => ouvrirPin(s)} title="Code PIN de connexion par WhatsApp"
                      className={`${ui.act.iconDark} mr-1`} data-testid={`pin-staff-${s.id}`}>
                      <KeyRound className="w-3.5 h-3.5" />
                    </button>
                  )}
                  {canEdit && (
                    // Modifier : bouton plein noir (design SAWALI)
                    <button type="button" onClick={() => openEdit(s)} title="Modifier" className={ui.act.iconDark} data-testid={`edit-staff-${s.id}`}>
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                  )}
                  {/* Désactiver / réinitialiser le mot de passe (jamais sur soi ; compte admin :
                      lui seul ; superviseur : superviseur ou admin) + Supprimer (superviseur) */}
                  {/* Accès temporaire (hors liste blanche) — pas utile pour superviseur/admin, jamais bloqués */}
                  {canIssueTokens && s.id !== me?.id && !isSupRow(s) && !isAdminAccountRow(s) && <TemporaryAccessButton account={s} />}
                  {s.id !== me?.id && (!isAdminAccountRow(s) || isAdminAccount) && (!isSupRow(s) || isSuperviseur || isAdminAccount) && (
                    <AccountActions account={s} onChanged={load} canManage={canEdit} deleteLabel="ce compte du personnel"
                      canDelete={isSuperviseur && !isAdminAccountRow(s) && (!isSupRow(s) || isAdminAccount)} />
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Lot 16 — fenêtre « Code PIN WhatsApp » d'un collaborateur */}
      <Dialog open={!!pinCible} onOpenChange={(v) => { if (!v) { setPinCible(null); setPinResultat(null); } }}>
        <DialogContent data-testid="pin-dialog">
          <DialogHeader><DialogTitle>Connexion par WhatsApp — {pinCible?.full_name}</DialogTitle></DialogHeader>
          {!pinResultat ? (
            <div className="space-y-3 text-sm">
              <p className="text-muted-foreground">
                Le collaborateur se connecte avec son <b>numéro WhatsApp</b> et un <b>code PIN à 4 chiffres</b>,
                puis saisit le code à 6 chiffres reçu par WhatsApp. Le PIN est affiché une seule fois ;
                seul son hachage est enregistré. Un nouveau PIN remplace l'ancien.
              </p>
              <div className="rounded-md border p-2 text-xs">
                Numéro utilisé : <b>{pinCible?.whatsapp_number || pinCible?.phone || "aucun — renseignez le téléphone (bouton Modifier)"}</b>
                <div className="mt-1">
                  État : {pins[pinCible?.id]
                    ? <>PIN actif depuis le {new Date(pins[pinCible.id].defini_le).toLocaleString("fr-FR")}{pins[pinCible.id].defini_par_nom ? ` (par ${pins[pinCible.id].defini_par_nom})` : ""}</>
                    : "aucun PIN"}
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <Checkbox checked={pinEnvoiWa} onCheckedChange={(v) => setPinEnvoiWa(!!v)} data-testid="pin-send-wa" />
                <span className="flex items-center gap-1"><MessageCircle className="w-4 h-4" /> Envoyer aussi le PIN au collaborateur par WhatsApp</span>
              </label>
            </div>
          ) : (
            <div className="space-y-3 text-sm" data-testid="pin-result">
              <p>Code PIN de <b>{pinCible?.full_name}</b> (numéro {pinResultat.numero_whatsapp}) :</p>
              <div className="flex items-center gap-2">
                <span className="font-mono text-3xl tracking-[0.4em] text-[#0B1912]" data-testid="pin-value">
                  {pinVisible ? pinResultat.pin : "••••"}
                </span>
                <button type="button" onClick={() => setPinVisible((v) => !v)} className="h-8 w-8 inline-flex items-center justify-center rounded text-muted-foreground hover:text-[#0F6B4A]"
                  title={pinVisible ? "Masquer le PIN" : "Afficher le PIN"} aria-label={pinVisible ? "Masquer le PIN" : "Afficher le PIN"}>
                  {pinVisible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {pinResultat.envoye_whatsapp === true && <p className="text-emerald-700 text-xs">Envoyé par WhatsApp au collaborateur.</p>}
              {pinResultat.envoye_whatsapp === false && <p className="text-amber-700 text-xs">L'envoi WhatsApp a échoué : remettez ce PIN au collaborateur en main propre.</p>}
              <p className="text-xs text-muted-foreground">Ce PIN ne sera plus jamais affiché. Connexion : page de connexion → « Par WhatsApp ».</p>
            </div>
          )}
          <DialogFooter className="flex-wrap gap-2">
            {!pinResultat && pins[pinCible?.id] && (
              <Button variant="outline" className="text-red-600 mr-auto" onClick={retirerPin} disabled={pinBusy} data-testid="pin-remove">
                <Trash2 className="w-4 h-4 mr-2" />Retirer le PIN
              </Button>
            )}
            <Button variant="outline" onClick={() => { setPinCible(null); setPinResultat(null); }}>Fermer</Button>
            {!pinResultat && (
              <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={genererPin} disabled={pinBusy} data-testid="pin-generate">
                {pinBusy ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <KeyRound className="w-4 h-4 mr-2" />}
                {pins[pinCible?.id] ? "Générer un nouveau PIN" : "Générer le PIN"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Création des comptes de test */}
      <Dialog open={openTest} onOpenChange={setOpenTest}>
        <DialogContent data-testid="test-accounts-dialog">
          <DialogHeader><DialogTitle>Comptes de test de la recette</DialogTitle></DialogHeader>
          {!testResult ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Crée TEST Secrétaire A, TEST Secrétaire B (caissière), TEST Collaborateur Formulaires, TEST Comptable,
                TEST Client 1 et TEST Client 2{isAdminAccount ? ", et TEST Superviseur" : ""}. Ils ne sont visibles que du superviseur.
                Chaque compte reçoit une adresse « +alias » de l'e-mail ci-dessous : tous les codes de connexion arrivent dans cette boîte.
              </p>
              <div><Label>E-mail qui recevra les codes de connexion</Label><Input value={testForm.email} onChange={(e) => setTestForm({ ...testForm, email: e.target.value })} data-testid="test-email" /></div>
              <div><Label>Mot de passe commun (8 caractères min.)</Label><div className="relative"><Input type={voirMdp ? "text" : "password"} className="pr-10" value={testForm.password} onChange={(e) => setTestForm({ ...testForm, password: e.target.value })} data-testid="test-password" /><BoutonOeil /></div></div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div><Label>WhatsApp Client 1 (+226…)</Label><Input value={testForm.client1_whatsapp} onChange={(e) => setTestForm({ ...testForm, client1_whatsapp: e.target.value })} placeholder="a écrit au cabinet < 24 h" /></div>
                <div><Label>WhatsApp Client 2 (+226…)</Label><Input value={testForm.client2_whatsapp} onChange={(e) => setTestForm({ ...testForm, client2_whatsapp: e.target.value })} placeholder="n'a pas écrit depuis 24 h" /></div>
              </div>
            </div>
          ) : (
            <div className="space-y-2 max-h-[50vh] overflow-y-auto" data-testid="test-accounts-result">
              {testResult.map((a) => (
                <div key={a.email} className="text-sm border rounded-md p-2">
                  <div className="font-medium">{a.name} <span className="text-xs text-muted-foreground">— {a.status}</span></div>
                  <div className="text-xs font-mono break-all">{a.email}</div>
                  {a.detail && <div className="text-xs text-amber-700">{a.detail}</div>}
                </div>
              ))}
              <p className="text-xs text-muted-foreground">Connexion : l'adresse ci-dessus + le mot de passe choisi ; le code arrive dans votre boîte.</p>
            </div>
          )}
          <DialogFooter className="flex-wrap gap-2">
            <Button variant="outline" className="text-red-600 mr-auto" onClick={deleteTestAccounts} disabled={testBusy} data-testid="delete-test-accounts">Supprimer les comptes de test</Button>
            <Button variant="outline" onClick={() => setOpenTest(false)}>Fermer</Button>
            {!testResult && <Button className="bg-[#0F6B4A] hover:bg-[#0A4E36] text-white" onClick={createTestAccounts} disabled={testBusy} data-testid="create-test-accounts">Créer / remettre à neuf</Button>}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
