/*
  Lot 89 — « Empreintes digitales » : écran réservé au DG.
  Le super-admin ACTIVE la fonction (Paramètres → Accès du personnel). Le DG, seul, gère les enrôlements :
    1. il choisit une personne et génère un CODE D'ENRÔLEMENT (15 minutes, usage unique) ;
    2. la personne ouvre la page de connexion sur son appareil, touche « J'ai un code d'enrôlement », saisit le code
       et pose son doigt : l'appareil est enregistré (le serveur ne garde qu'une clé publique, jamais l'empreinte) ;
    3. le DG peut retirer les appareils d'une personne (téléphone perdu, départ).
  API : GET /admin/passkeys, POST /admin/passkeys/invitations, DELETE /admin/passkeys/user/{id} (albarka_passkeys.py)
*/
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Fingerprint, KeyRound, Trash2, Search, Smartphone } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const fmt = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" }) : "jamais");

export default function AdminEmpreintes() {
  const [data, setData] = useState(null);
  const [erreur, setErreur] = useState("");
  const [recherche, setRecherche] = useState("");
  const [invitation, setInvitation] = useState(null);     // { code, nom, valable_minutes } affiché une seule fois
  const [occupe, setOccupe] = useState("");

  const charger = async () => {
    try {
      const { data: d } = await apiClient.get("/admin/passkeys");
      setData(d);
      setErreur("");
    } catch (err) {
      setErreur(extractError(err, "Accès refusé"));
    }
  };
  useEffect(() => { charger(); }, []);

  // Génère le code d'enrôlement d'une personne (montré une seule fois, à remettre de vive voix)
  const inviter = async (c) => {
    setOccupe(c.user_id);
    try {
      const { data: r } = await apiClient.post("/admin/passkeys/invitations", { user_id: c.user_id });
      setInvitation(r);
    } catch (err) { toast.error(extractError(err)); } finally { setOccupe(""); }
  };

  // Retire toutes les empreintes d'une personne
  const retirer = async (c) => {
    if (!window.confirm(`Retirer toutes les empreintes enregistrées de ${c.nom} ?`)) return;
    try {
      await apiClient.delete(`/admin/passkeys/user/${c.user_id}`);
      toast.success("Empreintes retirées");
      charger();
    } catch (err) { toast.error(extractError(err)); }
  };

  const comptes = useMemo(() => {
    const q = recherche.trim().toLowerCase();
    return (data?.comptes || []).filter((c) => !q || `${c.nom} ${c.email}`.toLowerCase().includes(q));
  }, [data, recherche]);

  if (erreur) return <div className="p-6 text-sm text-red-700" data-testid="empreintes-erreur">{erreur}</div>;
  if (!data) return <div className="p-6 text-sm text-muted-foreground">Chargement…</div>;

  return (
    <div className="space-y-5" data-testid="admin-empreintes">
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2"><Fingerprint className="w-6 h-6 text-[#0F6B4A]" /> Empreintes digitales</h1>
        <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
          Enrôlement des appareils pour la connexion par empreinte. Seul le DG gère cet écran ; le mot de passe avec code reste toujours possible.
        </p>
      </div>

      {!data.enabled && (
        <div className="albarka-card p-4 text-sm text-amber-800 bg-amber-50 border-amber-200" data-testid="empreintes-desactivee">
          La connexion par empreinte n'est pas activée. Le super-admin l'active dans Paramètres → Accès du personnel ; les enrôlements sont bloqués d'ici là.
        </div>
      )}

      {invitation && (
        <div className="albarka-card p-4 text-center space-y-2" data-testid="empreintes-invitation">
          <div className="text-sm">Code d'enrôlement de <b>{invitation.nom}</b> (valable {invitation.valable_minutes} minutes, usage unique)</div>
          <div className="text-3xl font-mono tracking-widest text-[#0F6B4A]" data-testid="empreintes-code">{invitation.code}</div>
          <div className="text-xs text-muted-foreground">
            Remettez-le à la personne : sur son appareil, page de connexion → « J'ai un code d'enrôlement ». Il ne sera plus affiché.
          </div>
          <Button variant="outline" size="sm" onClick={() => setInvitation(null)}>Fermer</Button>
        </div>
      )}

      <div className="relative max-w-sm">
        <Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground" />
        <Input className="pl-9" placeholder="Rechercher une personne…" value={recherche} onChange={(e) => setRecherche(e.target.value)} data-testid="empreintes-recherche" />
      </div>

      <div className="albarka-card overflow-x-auto">
        <table className="w-full text-sm tableau">
          <thead>
            <tr className="text-left border-b">
              <th className="p-3">Personne</th>
              <th className="p-3">Appareils enrôlés</th>
              <th className="p-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {comptes.map((c) => (
              <tr key={c.user_id} className="border-b last:border-0" data-testid={`empreinte-ligne-${c.user_id}`}>
                <td className="p-3">
                  <div className="font-medium">{c.nom}</div>
                  <div className="text-xs text-muted-foreground">{c.email}</div>
                </td>
                <td className="p-3">
                  {c.nb === 0 ? <span className="text-muted-foreground">Aucun</span> : c.appareils.map((a) => (
                    <div key={a.id} className="flex items-center gap-1 text-xs"><Smartphone className="w-3 h-3" /> {a.nom} — dernier usage : {fmt(a.dernier_usage)}</div>
                  ))}
                </td>
                <td className="p-3 text-right whitespace-nowrap">
                  <Button size="sm" variant="outline" disabled={!data.enabled || occupe === c.user_id || c.nb >= data.max_par_compte} onClick={() => inviter(c)} data-testid={`inviter-${c.user_id}`}>
                    <KeyRound className="w-4 h-4 mr-1" /> Code d'enrôlement
                  </Button>
                  {c.nb > 0 && (
                    <Button size="sm" variant="ghost" className="text-red-700" onClick={() => retirer(c)} data-testid={`retirer-${c.user_id}`}>
                      <Trash2 className="w-4 h-4 mr-1" /> Retirer
                    </Button>
                  )}
                </td>
              </tr>
            ))}
            {comptes.length === 0 && <tr><td colSpan={3} className="p-4 text-center text-muted-foreground">Aucune personne trouvée.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
