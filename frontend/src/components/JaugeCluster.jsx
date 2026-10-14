// ============================================================================
// Lot 27 — JAUGE DU CLUSTER DE PRODUCTION (MongoDB Atlas) dans la barre latérale du portail (administrateur),
// comme sur SAWALI : pastille « pictogramme base + point de couleur + % » ; un clic déplie le détail
// (taille occupée sur la limite du cluster, collections sur 500, taille par base du cluster).
// Couleurs : vert sous 45 % · orange à partir de 45 % · rouge à partir de 90 % (il reste 10 % ou moins).
// La mesure est gardée 10 min côté serveur ; relue ici toutes les 15 min, onglet visible seulement.
// ============================================================================
import { useCallback, useEffect, useState } from 'react'
import { apiClient as api } from '@/lib/api'

// Styles selon le niveau renvoyé par le serveur
const STYLES = {
  ok: { barre: 'bg-emerald-400', point: 'bg-emerald-400', texte: 'text-emerald-200' },
  attention: { barre: 'bg-amber-400', point: 'bg-amber-400', texte: 'text-amber-200' },
  plein: { barre: 'bg-rose-500', point: 'bg-rose-500 animate-pulse', texte: 'text-rose-200' },
}

// Pictogramme « base de données » (cylindre)
const Base = () => (
  <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
    <ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" /><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
  </svg>
)

// Lecture de la mesure (actif = administrateur seulement)
function useMesure(actif) {
  const [m, setM] = useState(null)
  const lire = useCallback(() => { api.get('/admin/atlas/jauge').then((r) => setM(r.data)).catch(() => setM(null)) }, [])
  useEffect(() => {
    if (!actif) return undefined
    lire()
    const t = setInterval(() => { if (document.visibilityState === 'visible') lire() }, 15 * 60 * 1000)
    return () => clearInterval(t)
  }, [actif, lire])
  return m
}

// Une barre d'occupation avec son texte
function Barre({ titre, part, niveau, texte }) {
  const st = STYLES[niveau] || STYLES.ok
  return (
    <div className="space-y-1">
      <p className="text-[10px] uppercase tracking-wider text-white/50">{titre}</p>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/10"><div className={`h-full rounded-full ${st.barre}`} style={{ width: `${Math.min(100, part)}%` }} /></div>
      <p className={`text-[11px] tabular-nums ${st.texte}`}>{texte}</p>
    </div>
  )
}

export default function JaugeCluster({ actif }) {
  const m = useMesure(actif)
  const [ouvert, setOuvert] = useState(false)
  if (!actif || !m) return null
  const st = STYLES[m.niveau] || STYLES.ok
  return (
    <div className="space-y-2">
      <button type="button" onClick={() => setOuvert((o) => !o)} aria-expanded={ouvert} data-testid="pastille-cluster"
              title={`Cluster de production : ${m.taille.total_mo} Mo sur ${m.taille.limite_mo} Mo, ${m.collections.total} collections sur ${m.collections.limite} — cliquez pour le détail`}
              className={`inline-flex items-center gap-1.5 rounded px-2 py-1 text-[11px] tabular-nums ring-1 transition-colors ${ouvert ? 'bg-white/15 text-white ring-white/30' : 'bg-white/5 text-white/70 ring-white/10 hover:bg-white/10'}`}>
        <Base /><span className={`inline-block h-2 w-2 rounded-full ${st.point}`} />{Math.round(m.pourcentage)} %
      </button>
      {ouvert && (
        <div className="space-y-2 border-t border-white/10 pt-2" data-testid="detail-cluster">
          <Barre titre="Taille sur le disque" part={m.taille.pourcentage} niveau={m.taille.niveau}
                 texte={`${m.taille.total_mo} / ${m.taille.limite_mo} Mo · ${m.taille.pourcentage} %${m.taille.niveau === 'plein' ? ' · presque plein !' : ''}`} />
          <Barre titre="Collections du cluster" part={m.collections.pourcentage} niveau={m.collections.niveau}
                 texte={`${m.collections.total} / ${m.collections.limite} · ${m.collections.pourcentage} %`} />
          <div className="space-y-0.5 border-t border-white/10 pt-1">
            {m.bases.map((b) => (
              <p key={b.nom} className="flex justify-between text-[10px] tabular-nums">
                <span className={`truncate ${b.courante ? 'font-semibold text-white' : 'text-white/50'}`}>{b.nom}</span>
                <span className="pl-2 text-white/70">{b.mo} Mo · {b.collections}</span>
              </p>
            ))}
            <p className="pt-0.5 text-[10px] text-white/40">Reste {m.taille.restant_mo} Mo · mesuré le {new Date(m.le).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</p>
          </div>
        </div>
      )}
    </div>
  )
}
