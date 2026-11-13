/*
  Lot 89 — Paramètres → « Accès du Client » (super-admin) : deux réglages de connexion.
    1. « Interdire l'accès aux clients sans contrat actif » — FAUX par défaut : un client sans contrat peut se connecter.
    2. « Connexion par empreinte digitale » — FAUX par défaut ; le super-admin l'active, mais seul le DG gère les enrôlements.
  Chaque interrupteur s'enregistre aussitôt (PUT /admin/settings). Props : settings, save(partial), saving.
*/
import React from "react";
import { Fingerprint, FileX } from "lucide-react";
import { Switch } from "@/components/ui/switch";

export default function AccesConnexionPanel({ settings, save, saving }) {
  return (
    <div className="albarka-card p-5 space-y-5 mb-6" data-testid="acces-connexion-panel">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="font-semibold flex items-center gap-2"><FileX className="w-4 h-4" /> Interdire l'accès aux clients sans contrat actif</div>
          <div className="text-sm text-muted-foreground max-w-xl">
            Désactivé (par défaut) : un client sans contrat actif peut se connecter à son espace. Activé : il reçoit « Aucun contrat actif »
            et doit contacter le cabinet.
          </div>
        </div>
        <Switch checked={!!settings.interdire_clients_sans_contrat} disabled={saving}
          onCheckedChange={(v) => save({ interdire_clients_sans_contrat: v })} data-testid="switch-interdire-sans-contrat" />
      </div>
      <div className="flex items-start justify-between gap-4 border-t pt-5">
        <div>
          <div className="font-semibold flex items-center gap-2"><Fingerprint className="w-4 h-4" /> Connexion par empreinte digitale</div>
          <div className="text-sm text-muted-foreground max-w-xl">
            Ajoute un bouton « Se connecter avec mon empreinte » sur la page de connexion (téléphone, Windows Hello, clé de sécurité).
            L'empreinte reste sur l'appareil. Une fois activée, <b>seul le DG</b> enrôle ou retire les appareils (menu « Empreintes digitales »).
            Le mot de passe avec code reste toujours possible.
          </div>
        </div>
        <Switch checked={!!settings.empreinte_activee} disabled={saving}
          onCheckedChange={(v) => save({ empreinte_activee: v })} data-testid="switch-empreinte" />
      </div>
    </div>
  );
}
