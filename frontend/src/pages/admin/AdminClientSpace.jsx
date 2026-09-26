/*
  « Dépôt espace client » — page rapide pour déposer des documents faits
  hors du portail (factures, rapports, attestations…) dans l'espace client.
  Deux modes :
    - « Un client » : on choisit le client, puis on utilise le même panneau
      que l'onglet « Espace client » de sa fiche (ClientSpacePanel) ;
    - « Plusieurs clients » : le même document (ex. note des impôts) est
      déposé en une fois chez tous les clients cochés (MultiClientUpload).
*/
import React, { useState } from "react";
import { User, Users } from "lucide-react";
import { Label } from "@/components/ui/label";
import EntitySelect from "@/components/EntitySelect";
import ClientSpacePanel from "@/components/ClientSpacePanel";
import MultiClientUpload from "@/components/MultiClientUpload";

export default function AdminClientSpace() {
  const [mode, setMode] = useState("one");     // "one" = un client, "many" = plusieurs clients
  const [tenantId, setTenantId] = useState(""); // client choisi (mode « Un client »)
  // Bouton de choix du mode (style onglet)
  const modeBtn = (key, Icon, label) => (
    <button type="button" onClick={() => setMode(key)} data-testid={`cs-mode-${key}`}
      className={`inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm border ${mode === key ? "bg-[#0F6B4A] text-white border-[#0F6B4A]" : "bg-white text-slate-700"}`}>
      <Icon className="w-4 h-4" /> {label}
    </button>
  );
  return (
    <div className="space-y-6" data-testid="admin-client-space-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
        <h1 className="font-display text-3xl md:text-4xl">Dépôt dans l'espace client</h1>
        <p className="text-muted-foreground mt-1">Factures, rapports, attestations… faits dans un autre logiciel ou scannés : le client les retrouve dans « Factures & documents » et il est prévenu par WhatsApp.</p>
      </div>
      {/* Choix du mode de dépôt */}
      <div className="flex flex-wrap gap-2">
        {modeBtn("one", User, "Un client")}
        {modeBtn("many", Users, "Plusieurs clients")}
      </div>
      {mode === "many" ? <MultiClientUpload /> : (
        <>
          <div className="w-full sm:w-80">
            <Label className="text-xs">Client</Label>
            <div className="mt-1"><EntitySelect value={tenantId} onChange={setTenantId} placeholder="Choisir un client" testId="cs-client-select" /></div>
          </div>
          {tenantId ? <ClientSpacePanel key={tenantId} tenantId={tenantId} /> : <p className="text-sm text-muted-foreground">Choisissez d'abord un client.</p>}
        </>
      )}
    </div>
  );
}
