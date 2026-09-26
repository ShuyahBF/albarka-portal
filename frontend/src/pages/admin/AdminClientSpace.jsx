/*
  « Dépôt espace client » — page rapide pour déposer des documents faits
  hors du portail (factures, rapports, attestations…) dans l'espace d'un
  client : on choisit le client, puis on utilise le même panneau que l'onglet
  « Espace client » de sa fiche (ClientSpacePanel).
*/
import React, { useState } from "react";
import { Label } from "@/components/ui/label";
import EntitySelect from "@/components/EntitySelect";
import ClientSpacePanel from "@/components/ClientSpacePanel";

export default function AdminClientSpace() {
  const [tenantId, setTenantId] = useState(""); // client choisi
  return (
    <div className="space-y-6" data-testid="admin-client-space-page">
      <div>
        <div className="text-xs uppercase tracking-[0.2em] text-[#0F6B4A] mb-2">Cabinet</div>
        <h1 className="font-display text-3xl md:text-4xl">Dépôt dans l'espace client</h1>
        <p className="text-muted-foreground mt-1">Factures, rapports, attestations… faits dans un autre logiciel ou scannés : le client les retrouve dans « Factures & documents » et il est prévenu par WhatsApp.</p>
      </div>
      <div className="w-full sm:w-80">
        <Label className="text-xs">Client</Label>
        <div className="mt-1"><EntitySelect value={tenantId} onChange={setTenantId} placeholder="Choisir un client" testId="cs-client-select" /></div>
      </div>
      {tenantId ? <ClientSpacePanel key={tenantId} tenantId={tenantId} /> : <p className="text-sm text-muted-foreground">Choisissez d'abord un client.</p>}
    </div>
  );
}
