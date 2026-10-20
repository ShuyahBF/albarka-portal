/*
  Lot 52 — « Synthèses du mois » du tableau de bord client : 4 cartes (Rapport RH, CNSS, Fiscal, Comptable) par mois.
  Les documents viennent du cabinet (dépôt dans l'espace client avec un thème). Un clic ouvre le document.
  Source : GET /me/space/syntheses (documents visibles du client connecté seulement).
*/
import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";
import { THEMES, libelleMois } from "@/components/synthese/themes";

export default function SynthesesMensuelles() {
  const [data, setData] = useState(null);
  const [mois, setMois] = useState("");

  useEffect(() => {
    apiClient.get("/me/space/syntheses")
      .then(({ data: d }) => { setData(d); setMois((m) => m || d.mois?.[0]?.periode || ""); })
      .catch(() => setData({ mois: [] }));          // facultatif : une erreur n'affiche simplement rien
  }, []);

  if (!data || !(data.mois || []).length) return null;      // aucune synthèse : la section n'apparaît pas
  const courant = data.mois.find((m) => m.periode === mois) || data.mois[0];

  const ouvrir = async (it) => {
    try {
      const res = await apiClient.get(`/me/space/${it.source}/${it.id}/file`, { responseType: "blob" });
      window.open(URL.createObjectURL(res.data), "_blank");
    } catch (err) { toast.error(extractError(err, "Ouverture impossible")); }
  };

  return (
    <section className="space-y-3" data-testid="syntheses-mensuelles">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-xl">Synthèses du mois</h2>
        <div className="flex flex-wrap gap-2">
          {data.mois.map((m) => (
            <button key={m.periode} type="button" onClick={() => setMois(m.periode)} data-testid={`synthese-mois-${m.periode}`}
                    className={`px-3 py-1 rounded-full text-sm border capitalize ${courant.periode === m.periode ? "bg-[#0F6B4A] text-white border-[#0F6B4A]" : "bg-white text-slate-700"}`}>
              {libelleMois(m.periode)} <span className="opacity-70">({m.total})</span>
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {THEMES.map((t) => {
          const items = courant.themes?.[t.key] || [];
          return (
            <div key={t.key} className="albarka-card p-4 min-w-0" data-testid={`synthese-carte-${t.key}`}>
              <div className="flex items-center justify-between">
                <div className="font-semibold">{t.emoji} {t.label}</div>
                <span className="albarka-chip bg-slate-100 text-slate-700 text-xs">{items.length}</span>
              </div>
              {items.length === 0 ? (
                <p className="mt-2 text-xs text-muted-foreground">Rien ce mois-ci.</p>
              ) : (
                <ul className="mt-2 space-y-1">
                  {items.map((it) => (
                    <li key={it.id}>
                      <button type="button" onClick={() => ouvrir(it)} className="w-full text-left text-sm hover:underline break-words" data-testid={`synthese-doc-${it.id}`}>
                        {it.title}{it.is_new && <span className="ml-1 albarka-chip text-[10px] bg-[#E5A24B]/20 text-[#8a5a14]">Nouveau</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
