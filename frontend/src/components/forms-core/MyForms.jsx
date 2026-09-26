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
import { ui, cx } from "./ui";

export default function MyForms({ portalApiBase = "/me/forms" }) {
  const [items, setItems] = useState(null);
  useEffect(() => { apiClient.get(portalApiBase).then((r) => setItems(r.data.items || [])).catch(() => setItems([])); }, [portalApiBase]);

  const todo = (items || []).filter((i) => !i.answered_at && !i.closed_reason).length;
  return (
    <div className="space-y-4" data-testid="my-forms">
      <div>
        <p className={ui.eyebrow}>Mon espace</p>
        <h1 className={ui.h1}><ClipboardList className={ui.h1Icon} /> Mes formulaires</h1>
        <p className={ui.subtitle}>{items === null ? "" : todo ? `${todo} formulaire(s) à remplir.` : "Vous êtes à jour : aucun formulaire en attente."}</p>
      </div>
      {items === null ? <p className={ui.loading}><Loader2 className="h-4 w-4 animate-spin inline mr-1" /> Chargement…</p> : items.length === 0 ? (
        <p className={ui.empty}>Vous n'avez reçu aucun formulaire.</p>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((i) => (
            <div key={i.id} className={cx(ui.card, "flex flex-col gap-2")} data-testid={`my-form-${i.id}`}>
              <div className="flex items-center justify-between">{i.answered_at ? <span className={ui.badge.green}><CheckCircle2 className="h-3 w-3" /> Répondu</span> : <span className={ui.badge.amber}><Clock className="h-3 w-3" /> À remplir</span>}</div>
              <div className="flex-1">
                <p className="text-sm font-display font-bold text-slate-900">{i.title}</p>
                <p className="text-[11px] text-slate-500 mt-1">Reçu le {formatDateTime(i.received_at)}{i.answered_at ? ` · répondu le ${formatDateTime(i.answered_at)}` : ""}{i.closed_reason ? ` · ${i.closed_reason}` : ""}</p>
              </div>
              {!i.closed_reason && (!i.answered_at || i.can_edit) && (
                <a href={i.path} className={cx(i.answered_at ? ui.act.dark : ui.act.primary, "self-start")}>{i.answered_at ? "Modifier ma réponse" : "Remplir"}</a>
              )}
              {i.answered_at && !i.can_edit && <span className="text-[11px] text-slate-400">Réponse envoyée</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
