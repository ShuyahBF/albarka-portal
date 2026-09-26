import React, { useEffect, useState, useMemo } from "react";
import { toast } from "sonner";
import { Plus, Pencil, FlaskConical } from "lucide-react";
import AccountActions, { AccountDates } from "@/components/AccountActions";
import { usePresence, PresenceLabel } from "@/components/Presence";
import TemporaryAccessButton from "@/components/TemporaryAccessButton";
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
  // Point 10 — filtrage selon le rôle du visiteur.
  const isAdmin = myRoles.includes("administrateur");
  const canEdit = isAdmin || myRoles.includes("superviseur") || myRoles.includes("direction");
  // Superviseur : supprime un compte du personnel, gère les comptes de test.
  const isSuperviseur = myRoles.includes("superviseur");
  // Compte admin du portail : SEUL habilité à cocher / décocher « Superviseur »
  // (doit rester identique à ADMIN_ACCOUNT_EMAIL côté backend).
  const isAdminAccount = (me?.email || "").toLowerCase() === "admin@sawalismartsystems.com";
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
                <div><Label>Mot de passe</Label><Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="staff-password-input" /></div>
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
              <TableHead>Connexion / modification</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Chargement…</TableCell></TableRow>}
            {!loading && visibleItems.length === 0 && <TableRow><TableCell colSpan={7} className="text-center py-10 text-muted-foreground">Aucun personnel.</TableCell></TableRow>}
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
                <TableCell>
                  <PresenceLabel presence={presence.items[s.id]} />
                  <AccountDates account={s} />
                </TableCell>
                <TableCell className="text-right whitespace-nowrap">
                  {canEdit && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => openEdit(s)}
                      title="Modifier"
                      data-testid={`edit-staff-${s.id}`}
                    >
                      <Pencil className="w-4 h-4" />
                    </Button>
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
              <div><Label>Mot de passe commun (8 caractères min.)</Label><Input type="password" value={testForm.password} onChange={(e) => setTestForm({ ...testForm, password: e.target.value })} data-testid="test-password" /></div>
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
