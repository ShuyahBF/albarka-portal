// « Fonctions des contacts » (lot 100) : la liste des FONCTIONS (DG, DAF, comptable…) que peut avoir un contact d'un client.
// Chaque fonction est un PROFIL : pour chaque option de l'espace client, deux cases à cocher — « Voir » (la rubrique apparaît) et « Agir » (déposer, modifier, supprimer).
// Liste commune à TOUS les clients ; réservée au DG et au super-administrateur (le serveur le vérifie aussi).
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Eye, Hand, Pencil, Plus, RefreshCw, Save, Trash2, X } from "lucide-react";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

export default function AdminFonctionsContacts() {
  const [fonctions, setFonctions] = useState([]);
  const [options, setOptions] = useState({});             // { code: libellé } des rubriques de l'espace client
  const [chargement, setChargement] = useState(true);
  const [edition, setEdition] = useState(null);           // null | { code?, libelle, voir[], agir[] }

  const charger = useCallback(async (manuel = false) => {
    if (manuel) toast.info("Actualisation des fonctions en cours…");               // règle 17 : toast « en cours » à chaque actualisation
    setChargement(true);
    try {
      const { data } = await apiClient.get("/fonctions-contacts");
      setFonctions(data.fonctions); setOptions(data.options);
      if (manuel) toast.success(`${data.fonctions.length} fonction(s) relue(s).`);
    } catch (err) { toast.error(extractError(err)); } finally { setChargement(false); }
  }, []);
  useEffect(() => { charger(); }, [charger]);

  // Case « voir » décochée : « agir » l'est aussi (on ne peut pas agir sur ce qu'on ne voit pas)
  const basculer = (champ, code) => setEdition((e) => {
    const a = new Set(e[champ]);
    a.has(code) ? a.delete(code) : a.add(code);
    const suite = { ...e, [champ]: [...a] };
    if (champ === "voir" && !a.has(code)) suite.agir = suite.agir.filter((x) => x !== code);
    if (champ === "agir" && a.has(code) && !suite.voir.includes(code)) suite.voir = [...suite.voir, code];
    return suite;
  });

  const enregistrer = async () => {
    if (!edition.libelle.trim() || edition.libelle.trim().length < 2) { toast.error("Donnez un nom à la fonction"); return; }
    try {
      if (edition.code) await apiClient.put(`/fonctions-contacts/${edition.code}`, { libelle: edition.libelle, voir: edition.voir, agir: edition.agir });
      else await apiClient.post("/fonctions-contacts", { libelle: edition.libelle, voir: edition.voir, agir: edition.agir });
      toast.success("Fonction enregistrée");
      setEdition(null); await charger();
    } catch (err) { toast.error(extractError(err)); }
  };

  const supprimer = async (f) => {
    if (!window.confirm(`Supprimer la fonction « ${f.libelle} » ?`)) return;
    try { await apiClient.delete(`/fonctions-contacts/${f.code}`); toast.success("Fonction supprimée"); await charger(); }
    catch (err) { toast.error(extractError(err)); }
  };

  const resume = (liste) => liste.length ? liste.map((c) => options[c] || c).join(", ") : "—";

  return (
    <div className="space-y-5" data-testid="fonctions-contacts">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1">
          <h1 className="text-2xl font-bold">Fonctions des contacts</h1>
          <p className="text-sm text-muted-foreground">Chaque fonction est un profil : pour chaque option de l'espace client, cochez ce que le contact peut <b>voir</b> et ce qu'il peut <b>faire</b>. La liste est commune à tous les clients.</p>
        </div>
        <Button variant="outline" onClick={() => charger(true)} title="Actualiser la liste des fonctions" aria-label="Actualiser" data-testid="fonctions-actualiser"><RefreshCw className="mr-1 h-4 w-4" />Actualiser</Button>
        <Button onClick={() => setEdition({ libelle: "", voir: [], agir: [] })} className="bg-[#0F6B4A] text-white hover:bg-[#0A4E36]" data-testid="fonction-nouvelle"><Plus className="mr-1 h-4 w-4" />Ajouter une fonction</Button>
      </div>

      <div className="overflow-x-auto rounded-xl border">
        <Table>
          <TableHeader><TableRow><TableHead>Fonction</TableHead><TableHead><Eye className="mr-1 inline h-4 w-4" />Peut voir</TableHead><TableHead><Hand className="mr-1 inline h-4 w-4" />Peut agir</TableHead><TableHead className="text-right">Actions</TableHead></TableRow></TableHeader>
          <TableBody>
            {chargement && <TableRow><TableCell colSpan={4} className="py-8 text-center text-muted-foreground">Chargement…</TableCell></TableRow>}
            {fonctions.map((f) => (
              <TableRow key={f.code}>
                <TableCell className="font-medium text-[#0B4F8A]">{f.libelle}</TableCell>
                <TableCell className="text-sm">{resume(f.voir)}</TableCell>
                <TableCell className="text-sm text-emerald-800">{resume(f.agir)}</TableCell>
                <TableCell className="whitespace-nowrap text-right">
                  <Button variant="ghost" size="sm" title="Modifier la fonction" aria-label="Modifier" onClick={() => setEdition({ code: f.code, libelle: f.libelle, voir: f.voir, agir: f.agir })}><Pencil className="h-4 w-4" /></Button>
                  <Button variant="ghost" size="sm" title="Supprimer la fonction" aria-label="Supprimer" onClick={() => supprimer(f)}><Trash2 className="h-4 w-4 text-red-600" /></Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={!!edition} onOpenChange={(o) => !o && setEdition(null)}>
        <DialogContent className="max-h-[85dvh] max-w-xl overflow-y-auto" data-testid="fonction-dialogue">
          <DialogHeader><DialogTitle>{edition?.code ? "Modifier la fonction" : "Nouvelle fonction"}</DialogTitle></DialogHeader>
          {edition && (
            <div className="space-y-4">
              <div><Label>Nom de la fonction</Label><Input value={edition.libelle} placeholder="Ex. Trésorier" onChange={(e) => setEdition({ ...edition, libelle: e.target.value })} data-testid="fonction-libelle" /></div>
              <div>
                <Label>Options de l'espace client</Label>
                <div className="mt-2 divide-y rounded-lg border">
                  <div className="grid grid-cols-[1fr_5rem_5rem] items-center gap-2 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-600"><span>Option</span><span className="text-center"><Eye className="mx-auto h-4 w-4" aria-label="Voir" /></span><span className="text-center"><Hand className="mx-auto h-4 w-4" aria-label="Agir" /></span></div>
                  {Object.entries(options).map(([code, libelle]) => (
                    <div key={code} className="grid grid-cols-[1fr_5rem_5rem] items-center gap-2 px-3 py-2 text-sm">
                      <span>{libelle}</span>
                      <span className="flex justify-center"><Checkbox checked={edition.voir.includes(code)} onCheckedChange={() => basculer("voir", code)} aria-label={`Voir : ${libelle}`} data-testid={`voir-${code}`} /></span>
                      <span className="flex justify-center"><Checkbox checked={edition.agir.includes(code)} onCheckedChange={() => basculer("agir", code)} aria-label={`Agir : ${libelle}`} data-testid={`agir-${code}`} /></span>
                    </div>
                  ))}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">« Agir » = déposer, modifier, supprimer ; cocher « Agir » coche aussi « Voir ». Une option fermée pour un client reste fermée pour ses contacts.</p>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEdition(null)}><X className="mr-1 h-4 w-4" />Annuler</Button>
            <Button onClick={enregistrer} className="bg-[#0F6B4A] text-white hover:bg-[#0A4E36]" data-testid="fonction-enregistrer"><Save className="mr-1 h-4 w-4" />Enregistrer</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
