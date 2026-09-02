// Affiche la synthèse IA d'un document : statut, résumé, champs extraits,
// alertes. Utilisé à la fois côté client et côté staff.
import { Badge } from "@/components/ui/badge";

const STATUS_LABELS = {
  recu: { label: "Reçu", variant: "outline" },
  en_analyse: { label: "Analyse en cours...", variant: "secondary" },
  analyse: { label: "Analysé", variant: "default" },
  erreur_analyse: { label: "Erreur d'analyse", variant: "destructive" },
};

export function StatusBadge({ status }) {
  const info = STATUS_LABELS[status] || { label: status, variant: "outline" };
  return <Badge variant={info.variant}>{info.label}</Badge>;
}

export default function DocumentSynthesis({ document }) {
  const synthesis = document?.synthesis;

  if (!synthesis) {
    return <p className="text-sm text-muted-foreground">Analyse en cours ou pas encore disponible.</p>;
  }

  const fields = Object.entries(synthesis.extracted_fields || {});

  return (
    <div className="space-y-4">
      {synthesis.document_type_guess && (
        <p className="text-sm">
          <span className="font-medium">Type détecté : </span>
          {synthesis.document_type_guess}
        </p>
      )}

      {synthesis.summary && (
        <div>
          <p className="font-medium text-sm mb-1">Synthèse</p>
          <p className="text-sm text-slate-700 whitespace-pre-wrap">{synthesis.summary}</p>
        </div>
      )}

      {fields.length > 0 && (
        <div>
          <p className="font-medium text-sm mb-1">Informations extraites</p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            {fields.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-muted-foreground">{key}</dt>
                <dd className="font-medium">{String(value)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {synthesis.flags?.length > 0 && (
        <div>
          <p className="font-medium text-sm mb-1 text-amber-700">Alertes</p>
          <ul className="list-disc list-inside text-sm text-amber-700">
            {synthesis.flags.map((flag, i) => (
              <li key={i}>{flag}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
