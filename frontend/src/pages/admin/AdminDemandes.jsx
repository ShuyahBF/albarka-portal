/*
  « Demandes de services » (cabinet, lot 53) — toutes les demandes reçues (clients connectés et visiteurs),
  filtrables par statut et service. Écoute de la note vocale, ouverture des pièces, changement de statut.
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { STATUTS, LIBELLES } from "@/pages/portal/Demandes";

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "");
const TOUS = "tous";

export default function AdminDemandes() {
  const [liste, setListe] = useState(null);
  const [statut, setStatut] = useState(TOUS);
  const [service, setService] = useState(TOUS);
  const [vocaux, setVocaux] = useState({});                 // id -> URL locale de la note vocale chargée

  const charger = () => apiClient.get("/demandes/admin", { params: {
    ...(statut !== TOUS ? { statut } : {}), ...(service !== TOUS ? { service } : {}) } })
    .then(({ data }) => setListe(data)).catch((e) => { toast.error(extractError(e)); setListe([]); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { charger(); }, [statut, service]);

  const changer = async (d, status) => {
    try { await apiClient.patch(`/demandes/admin/${d.id}`, { status }); charger(); }
    catch (e) { toast.error(extractError(e)); }
  };
  // Télécharge un fichier (index ou « vocal ») via la route protégée
  const blob = async (d, quoi) => (await apiClient.get(`/demandes/${d.id}/fichier/${quoi}`, { responseType: "blob" })).data;
  const ouvrir = async (d, f) => {
    try { window.open(URL.createObjectURL(await blob(d, f.index)), "_blank"); } catch (e) { toast.error(extractError(e, "Ouverture impossible")); }
  };
  const ecouter = async (d) => {
    try { const b = await blob(d, "vocal"); setVocaux((v) => ({ ...v, [d.id]: URL.createObjectURL(b) })); }
    catch (e) { toast.error(extractError(e, "Lecture impossible")); }
  };

  return (
    <div className="space-y-5" data-testid="admin-demandes-page">
      <div>
        <h1 className="font-display text-3xl">Demandes de services</h1>
        <p className="text-muted-foreground mt-1">Demandes envoyées par les clients et les visiteurs du site.</p>
      </div>
      <div className="flex flex-wrap gap-3">
        <Select value={statut} onValueChange={setStatut}>
          <SelectTrigger className="w-48"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={TOUS}>Tous les statuts</SelectItem>
            {Object.entries(STATUTS).map(([k, v]) => <SelectItem key={k} value={k}>{v[0]}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={service} onValueChange={setService}>
          <SelectTrigger className="w-56"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={TOUS}>Tous les services</SelectItem>
            {Object.entries(LIBELLES).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      {liste === null ? <div className="text-sm text-muted-foreground">Chargement…</div>
        : !liste.length ? <div className="text-sm text-muted-foreground">Aucune demande.</div>
        : (
          <div className="space-y-3">
            {liste.map((d) => (
              <div key={d.id} className="rounded-lg border bg-white p-4 text-sm space-y-2" data-testid="demande-admin">
                <div className="flex flex-wrap items-center gap-2">
                  <b>{LIBELLES[d.service] || d.service}</b>
                  {d.urgent && <span className="px-2 py-0.5 rounded-full text-xs bg-rose-100 text-rose-800">Urgent</span>}
                  <span className="px-2 py-0.5 rounded-full text-xs bg-slate-100">{d.origine === "public" ? "Visiteur" : "Client"}</span>
                  <span className="text-muted-foreground ml-auto">{fmtDate(d.created_at)}</span>
                </div>
                <div>{d.demandeur?.nom} · {d.demandeur?.telephone} {d.demandeur?.email && `· ${d.demandeur.email}`}</div>
                {d.description && <p className="whitespace-pre-wrap text-slate-700">{d.description}</p>}
                {d.vocal && (vocaux[d.id]
                  ? <audio controls autoPlay src={vocaux[d.id]} className="h-9" />
                  : <button type="button" className="text-[#0F6B4A] font-medium" onClick={() => ecouter(d)}>▶ Écouter la note vocale</button>)}
                {!!d.fichiers?.length && (
                  <div className="flex flex-wrap gap-3">
                    {d.fichiers.map((f) => <button key={f.index} type="button" className="text-[#0F6B4A] underline" onClick={() => ouvrir(d, f)}>{f.nom}</button>)}
                  </div>
                )}
                <Select value={d.status} onValueChange={(s) => changer(d, s)}>
                  <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
                  <SelectContent>{Object.entries(STATUTS).map(([k, v]) => <SelectItem key={k} value={k}>{v[0]}</SelectItem>)}</SelectContent>
                </Select>
              </div>
            ))}
          </div>
        )}
    </div>
  );
}
