// « Parcours des contacts » (lot 105) : journal de TOUT ce que font les contacts des clients sur le portail (connexions, pages, actions, refus), par client et par période.
// Réservé au DG et au super-administrateur (le serveur le vérifie aussi). Données : GET /journal-contacts (albarka_fonctions_contacts.py).
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Download, History, RefreshCw } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import NomClient, { libelleClient } from "@/components/NomClient";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const TYPES = { connexion: "Connexion", page: "Page", action: "Action", refus: "Refus" };
const COULEURS = { connexion: "bg-sky-100 text-sky-800", page: "bg-slate-100 text-slate-700", action: "bg-emerald-100 text-emerald-800", refus: "bg-red-100 text-red-800" };
const TOUS = "tous";
const CONTACTS = "contacts", SUPERADMIN = "superadmin";

export default function AdminJournalContacts() {
  const { user } = useAuth();
  const estDg = (user?.roles || []).includes("dg");     // seul le DG voit le parcours du super-administrateur
  const [quoi, setQuoi] = useState(CONTACTS);            // contacts des clients | super-administrateur
  const [clients, setClients] = useState([]);
  const [client, setClient] = useState(TOUS);
  const [type, setType] = useState(TOUS);
  const [du, setDu] = useState("");
  const [au, setAu] = useState("");
  const [lignes, setLignes] = useState(null);

  useEffect(() => { apiClient.get("/clients").then(({ data }) => setClients(data)).catch((e) => toast.error(extractError(e))); }, []);
  const parId = useMemo(() => Object.fromEntries(clients.map((c) => [c.id, c])), [clients]);

  const charger = useCallback(async (manuel = false) => {
    if (manuel) toast.info("Actualisation du parcours en cours…");              // règle 17 : toast « en cours » puis résultat
    try {
      const params = { limit: 500 };
      if (quoi === CONTACTS && client !== TOUS) params.client_id = client;
      if (du) params.du = du;
      if (au) params.au = au;
      const { data } = await apiClient.get(quoi === SUPERADMIN ? "/journal-superadmin" : "/journal-contacts", { params });
      setLignes(data.journal);
      if (manuel) toast.success(`${data.journal.length} ligne(s) lue(s).`);
    } catch (e) { toast.error(extractError(e)); setLignes([]); }
  }, [quoi, client, du, au]);
  useEffect(() => { charger(); }, [charger]);

  const affichees = (lignes || []).filter((l) => type === TOUS || l.type === type);
  const compte = (t) => (lignes || []).filter((l) => l.type === t).length;

  // Export CSV (à ouvrir dans Excel) : mêmes lignes que l'écran
  const exporter = () => {
    const echap = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = ["Date;Client;Contact;Fonction;Type;Méthode;Chemin;Résultat;Motif;IP"].concat(affichees.map((l) =>
      [new Date(l.at).toLocaleString("fr-FR"), parId[l.client_id] ? libelleClient(parId[l.client_id]) : l.client_id, l.nom, l.fonction, TYPES[l.type] || l.type, l.methode, l.chemin, l.statut, l.motif, l.ip].map(echap).join(";"))).join("\n");
    const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a"); a.href = url; a.download = "parcours-contacts.csv"; a.click(); URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-5" data-testid="journal-contacts">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1">
          <h1 className="flex items-center gap-2 text-2xl font-bold"><History className="h-6 w-6 text-[#0B4F8A]" />Parcours des contacts</h1>
          <p className="text-sm text-muted-foreground">Connexions, pages ouvertes, actions et refus des contacts des clients (180 jours conservés).</p>
        </div>
        <Button variant="outline" onClick={() => charger(true)} title="Relire le parcours" data-testid="journal-actualiser"><RefreshCw className="mr-1 h-4 w-4" />Actualiser</Button>
        <Button variant="outline" onClick={exporter} disabled={!affichees.length} title="Exporter les lignes affichées en CSV" data-testid="journal-export"><Download className="mr-1 h-4 w-4" />Exporter</Button>
      </div>

      {estDg && (
        <div className="flex gap-2" data-testid="journal-quoi">
          <Button variant={quoi === CONTACTS ? "default" : "outline"} size="sm" onClick={() => { setQuoi(CONTACTS); setLignes(null); }}>Contacts des clients</Button>
          <Button variant={quoi === SUPERADMIN ? "default" : "outline"} size="sm" onClick={() => { setQuoi(SUPERADMIN); setLignes(null); }} data-testid="journal-superadmin">Super-administrateur</Button>
        </div>
      )}
      {quoi === SUPERADMIN && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Parcours du super-administrateur : connexions, pages ouvertes et actions. Visible du DG seulement.</p>}

      <div className="grid gap-3 md:grid-cols-4">
        {quoi === CONTACTS ? (<div>
          <Label>Client</Label>
          <Select value={client} onValueChange={setClient}>
            <SelectTrigger data-testid="journal-client"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={TOUS}>Tous les clients</SelectItem>{clients.map((c) => <SelectItem key={c.id} value={c.id}><NomClient client={c} /></SelectItem>)}</SelectContent>
          </Select>
        </div>) : <div />}
        <div>
          <Label>Type</Label>
          <Select value={type} onValueChange={setType}>
            <SelectTrigger data-testid="journal-type"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value={TOUS}>Tous les types</SelectItem>{Object.entries(TYPES).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <div><Label>Du</Label><Input type="date" value={du} onChange={(e) => setDu(e.target.value)} /></div>
        <div><Label>Au</Label><Input type="date" value={au} onChange={(e) => setAu(e.target.value)} /></div>
      </div>

      {lignes && (
        <div className="flex flex-wrap gap-2 text-sm">
          {Object.entries(TYPES).map(([k, v]) => <span key={k} className={`rounded-full px-3 py-1 ${COULEURS[k]}`}>{v} : <b>{compte(k)}</b></span>)}
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border">
        <Table>
          <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Client</TableHead><TableHead>Contact</TableHead><TableHead>Type</TableHead><TableHead>Détail</TableHead><TableHead>Adresse</TableHead></TableRow></TableHeader>
          <TableBody>
            {lignes === null && <TableRow><TableCell colSpan={6} className="py-8 text-center text-muted-foreground">Chargement…</TableCell></TableRow>}
            {lignes && affichees.length === 0 && <TableRow><TableCell colSpan={6} className="py-8 text-center text-muted-foreground">Aucune trace pour ces critères.</TableCell></TableRow>}
            {affichees.map((l) => (
              <TableRow key={l.id}>
                <TableCell className="whitespace-nowrap text-sm">{new Date(l.at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</TableCell>
                <TableCell className="text-sm font-medium text-[#0B4F8A]">{parId[l.client_id] ? <NomClient client={parId[l.client_id]} /> : (l.client_id || "—")}</TableCell>
                <TableCell className="text-sm">{l.nom}<span className="block text-xs text-muted-foreground">{l.fonction}</span></TableCell>
                <TableCell><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${COULEURS[l.type] || ""}`}>{TYPES[l.type] || l.type}{l.type === "connexion" && l.connexion ? ` (${l.connexion})` : ""}</span></TableCell>
                <TableCell className="text-xs"><span className="font-mono">{l.methode} {l.chemin}</span>{l.motif && <span className="block text-red-700">{l.motif}</span>}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{l.ip}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
