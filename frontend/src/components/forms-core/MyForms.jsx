/*
  forms-core — module commun (NE PAS MODIFIER DANS UN SITE).

  MyForms : dans l'espace client, les formulaires reçus du cabinet, avec leur
  statut (à remplir / répondu / clos) et un bouton pour les remplir.

  Props : portalApiBase ("/me/forms")
*/
import React, { useEffect, useState } from "react";
import { ClipboardList, CheckCircle2, Clock, Loader2 } from "lucide-react";
import { apiClient } from "@/lib/api";
import { formatDateTime } from "./fieldTypes";

export default function MyForms({ portalApiBase = "/me/forms" }) {
  const [items, setItems] = useState(null);
  useEffect(() => { apiClient.get(portalApiBase).then((r) => setItems(r.data.items || [])).catch(() => setItems([])); }, [portalApiBase]);

  const todo = (items || []).filter((i) => !i.answered_at && !i.closed_reason).length;
  return (
    <div className="space-y-4" data-testid="my-forms">
      <div>
        <h1 className="text-2xl font-display font-semibold inline-flex items-center gap-2"><ClipboardList className="h-6 w-6 text-primary" /> Mes formulaires</h1>
        <p className="text-sm text-slate-600">{items === null ? "" : todo ? `${todo} formulaire(s) à remplir.` : "Vous êtes à jour : aucun formulaire en attente."}</p>
      </div>
      {items === null ? <p className="text-sm text-slate-500 inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Chargement…</p> : items.length === 0 ? (
        <p className="text-sm text-slate-400 py-10 text-center">Vous n'avez reçu aucun formulaire.</p>
      ) : (
        <div className="space-y-2">
          {items.map((i) => (
            <div key={i.id} className="rounded-xl border border-slate-200 bg-white p-4 flex flex-wrap items-center gap-3" data-testid={`my-form-${i.id}`}>
              {i.answered_at ? <CheckCircle2 className="h-6 w-6 text-emerald-600" /> : <Clock className="h-6 w-6 text-amber-500" />}
              <div className="flex-1 min-w-[200px]">
                <p className="font-medium">{i.title}</p>
                <p className="text-xs text-slate-500">Reçu le {formatDateTime(i.received_at)}{i.answered_at ? ` · répondu le ${formatDateTime(i.answered_at)}` : ""}{i.closed_reason ? ` · ${i.closed_reason}` : ""}</p>
              </div>
              {!i.closed_reason && (!i.answered_at || i.can_edit) && (
                <a href={i.path} className="rounded-lg bg-primary text-primary-foreground px-4 py-2 text-sm font-medium">{i.answered_at ? "Modifier ma réponse" : "Remplir"}</a>
              )}
              {i.answered_at && !i.can_edit && <span className="text-xs text-emerald-700 font-medium">Répondu</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
