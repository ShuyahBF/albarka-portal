// ============================================================================
// SupportPictos.jsx — SAWALI lot 93 : pictogrammes de la fenêtre d'assistance, comme dans le chat SAWALI.
//
// Demande du propriétaire (09/10/2026) : « Et ces pictos et leurs actions dans la fenêtre de chat au support
// pour les autres plateformes » (capture du chat SAWALI : image, trombone, palette, calendrier, micro, emojis).
//
//   😊 Emojis    : insère un emoji dans le message en cours ;
//   🖼️ Photo     : choisit une photo (ou l'appareil photo sur téléphone), réduite à 1 600 px avant l'envoi ;
//   📎 Trombone  : document (PDF, Word, Excel, PowerPoint, texte, CSV) ou vidéo MP4/WebM ;
//   🎤 Micro     : note vocale → texte (transcription automatique), ajouté au message pour relecture.
//   🖥️ Capture   : capture de l'écran (l'utilisateur choisit l'écran, la fenêtre ou l'onglet à montrer), envoyée
//                 comme une photo — demande du propriétaire du 10/10/2026 (ordinateur seulement).
// Le texte déjà saisi part comme légende de la photo ou du document.
// La palette (image IA) et le calendrier (disponibilités) restent des outils de l'ÉQUIPE du support dans SAWALI :
// leurs résultats (image, lien d'agenda) s'affichent ici comme n'importe quelle réponse.
//
// Composants exportés (aucune dépendance en dehors de React) :
//   <BarrePictos api texte setTexte desactive onEnvoye onErreur />  — la rangée de pictogrammes ;
//   <PieceJointe api media moi />                                    — photo / document / vidéo d'un message.
// `api` = client axios de la plateforme (jeton de connexion) : routes /support-sawali/fichier, /transcrire, /media.
// ============================================================================
import { useEffect, useRef, useState } from 'react'

const COTE_MAX = 1600                       // photo réduite à 1 600 px (côté le plus long)
const TAILLE_MAX = 15 * 1024 * 1024         // 15 Mo (limite de SAWALI pour un fichier relayé)
const DUREE_MAX_NOTE_MS = 120000            // note vocale : 2 minutes au plus
const TYPES_TROMBONE = 'video/mp4,video/webm,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,image/*'

// Emojis proposés (les plus utiles dans une discussion avec le support)
const EMOJIS = ['😀', '😊', '🙂', '😉', '😍', '🤔', '😅', '😂', '😢', '😡', '😮', '🙏',
  '👍', '👎', '👌', '👏', '🙌', '💪', '✅', '❌', '⚠️', '❓', '❗', '💡',
  '🔥', '⭐', '🎉', '❤️', '📌', '📎', '📄', '📷', '🖨️', '💻', '📱', '⏳',
  '🕐', '📅', '💰', '🧾', '🚗', '🛠️', '🔒', '🔑', '📞', '✉️', '👋', '🤝']

// --- Fichier → « data URL » (texte base64) prête à être envoyée dans le corps JSON
const lireDataUrl = (fichier) => new Promise((ok, ko) => {
  const l = new FileReader()
  l.onerror = () => ko(new Error('Lecture du fichier impossible.'))
  l.onload = () => ok(l.result)
  l.readAsDataURL(fichier)
})

// --- Photo réduite à 1 600 px en JPEG (une photo de téléphone pèse souvent 4 à 8 Mo)
const reduirePhoto = (fichier) => new Promise((ok, ko) => {
  const img = new Image()
  const url = URL.createObjectURL(fichier)
  img.onerror = () => { URL.revokeObjectURL(url); ko(new Error('Photo illisible.')) }
  img.onload = () => {
    const echelle = Math.min(1, COTE_MAX / Math.max(img.width, img.height))
    const toile = document.createElement('canvas')
    toile.width = Math.round(img.width * echelle)
    toile.height = Math.round(img.height * echelle)
    const ctx = toile.getContext('2d')
    ctx.fillStyle = '#ffffff'                       // fond blanc (PNG transparent → JPEG)
    ctx.fillRect(0, 0, toile.width, toile.height)
    ctx.drawImage(img, 0, 0, toile.width, toile.height)
    URL.revokeObjectURL(url)
    ok(toile.toDataURL('image/jpeg', 0.82))
  }
  img.src = url
})

// --- Pictogrammes (traits fins, couleur du texte)
const Icone = ({ d, ...p }) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...p}>{d}</svg>
)
const IcoPhoto = () => <Icone d={<><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21" /></>} />
const IcoTrombone = () => <Icone d={<path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" />} />
const IcoMicro = () => <Icone d={<><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><path d="M12 19v3" /></>} />
const IcoStop = () => <Icone d={<rect x="6" y="6" width="12" height="12" rx="1" fill="currentColor" />} />
const IcoCapture = () => <Icone d={<><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></>} />
const IcoEmoji = () => <Icone d={<><circle cx="12" cy="12" r="10" /><path d="M8 14s1.5 2 4 2 4-2 4-2" /><path d="M9 9h.01M15 9h.01" /></>} />

const classeBouton = 'inline-flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600 transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-40'

// ============================================================================
// Rangée de pictogrammes (au-dessus de la zone de saisie)
// ============================================================================
export function BarrePictos({ api, texte, setTexte, desactive = false, onEnvoye, onErreur }) {
  const [emojisOuverts, setEmojisOuverts] = useState(false)
  const [occupe, setOccupe] = useState('')          // '', 'envoi', 'enregistrement', 'transcription'
  const [progression, setProgression] = useState(0)
  const photoRef = useRef(null)
  const tromboneRef = useRef(null)
  const enregistreurRef = useRef(null)
  const morceauxRef = useRef([])
  const minuterieRef = useRef(null)

  // Arrêt propre du micro si la fenêtre se ferme pendant un enregistrement
  useEffect(() => () => {
    clearTimeout(minuterieRef.current)
    const e = enregistreurRef.current
    if (e && e.state !== 'inactive') { e.onstop = null; e.stop(); e.stream?.getTracks().forEach((p) => p.stop()) }
  }, [])

  // Envoi d'une photo ou d'un fichier (le texte saisi part comme légende)
  const envoyerFichier = async (fichier, estPhoto) => {
    if (!fichier) return
    onErreur?.('')
    setOccupe('envoi'); setProgression(0)
    try {
      const image = fichier.type.startsWith('image/')
      if (!image && fichier.size > TAILLE_MAX) throw new Error('Fichier trop volumineux (15 Mo au plus).')
      const contenu = image ? await reduirePhoto(fichier) : await lireDataUrl(fichier)
      const nom = image && !/\.jpe?g$/i.test(fichier.name) ? `${(fichier.name || 'photo').replace(/\.[^.]+$/, '')}.jpg` : (fichier.name || 'fichier')
      await api.post('/support-sawali/fichier', { fichier: contenu, nom, legende: (texte || '').trim() }, {
        timeout: 120000,
        onUploadProgress: (e) => { if (e.total) setProgression(Math.round((e.loaded * 100) / e.total)) },
      })
      setTexte('')
      await onEnvoye?.()
    } catch (err) {
      onErreur?.(err?.response?.data?.detail || err?.message || 'Envoi du fichier impossible.')
    } finally {
      setOccupe(''); setProgression(0)
      if (estPhoto && photoRef.current) photoRef.current.value = ''
      if (!estPhoto && tromboneRef.current) tromboneRef.current.value = ''
    }
  }

  // Note vocale : 1er clic = enregistrer, 2e clic = arrêter et transcrire
  const basculerMicro = async () => {
    if (occupe === 'enregistrement') { enregistreurRef.current?.stop(); return }
    onErreur?.('')
    if (!navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder === 'undefined') {
      onErreur?.("Ce navigateur ne permet pas l'enregistrement vocal."); return
    }
    try {
      const flux = await navigator.mediaDevices.getUserMedia({ audio: true })
      const enr = new MediaRecorder(flux)
      morceauxRef.current = []
      enr.ondataavailable = (e) => { if (e.data?.size) morceauxRef.current.push(e.data) }
      enr.onstop = async () => {
        clearTimeout(minuterieRef.current)
        flux.getTracks().forEach((p) => p.stop())
        const blob = new Blob(morceauxRef.current, { type: enr.mimeType || 'audio/webm' })
        if (!blob.size) { setOccupe(''); return }
        setOccupe('transcription')
        try {
          const audio = await lireDataUrl(blob)
          const r = await api.post('/support-sawali/transcrire', { audio, nom: (blob.type || '').includes('mp4') ? 'note.mp4' : 'note.webm' }, { timeout: 120000 })
          const t = (r.data?.texte || '').trim()
          if (t) setTexte((avant) => (avant ? `${avant.trim()} ${t}` : t))
          else onErreur?.('Aucun texte reconnu : réessayez plus distinctement.')
        } catch (err) {
          onErreur?.(err?.response?.data?.detail || 'Transcription impossible pour le moment.')
        } finally { setOccupe('') }
      }
      enregistreurRef.current = enr
      enr.start()
      setOccupe('enregistrement')
      minuterieRef.current = setTimeout(() => { if (enr.state !== 'inactive') enr.stop() }, DUREE_MAX_NOTE_MS)
    } catch {
      onErreur?.("Micro refusé ou indisponible : autorisez le micro pour ce site.")
    }
  }

  // Capture d'écran : le navigateur demande quel écran / quelle fenêtre / quel onglet montrer, on en prend UNE
  // image, puis le partage s'arrête aussitôt ; l'image part comme une photo (le texte saisi sert de légende).
  // Indisponible sur téléphone (le navigateur ne le permet pas) : le bouton n'est alors pas affiché.
  const captureDisponible = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getDisplayMedia
  const capturerEcran = async () => {
    onErreur?.('')
    let flux = null
    try {
      flux = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false })
      const video = document.createElement('video')
      video.srcObject = flux
      video.muted = true
      await video.play()
      await new Promise((ok) => setTimeout(ok, 300))          // première image bien affichée
      const toile = document.createElement('canvas')
      toile.width = video.videoWidth
      toile.height = video.videoHeight
      toile.getContext('2d').drawImage(video, 0, 0)
      const blob = await new Promise((ok) => toile.toBlob(ok, 'image/png'))
      if (!blob) throw new Error('capture vide')
      await envoyerFichier(new File([blob], `capture-${Date.now()}.png`, { type: 'image/png' }), true)
    } catch (err) {
      // L'utilisateur a annulé le choix de l'écran : rien à signaler
      if (err?.name !== 'NotAllowedError' && err?.name !== 'AbortError') onErreur?.("Capture d'écran impossible sur ce navigateur.")
    } finally {
      flux?.getTracks().forEach((p) => p.stop())
    }
  }

  const bloque = desactive || (occupe !== '' && occupe !== 'enregistrement')
  return (
    <div className="relative border-t border-slate-200 px-2 pt-2">
      {/* Indications pendant l'envoi, l'enregistrement ou la transcription */}
      {occupe === 'envoi' && <p className="mb-1 text-xs text-sky-700">Patientez… envoi du fichier {progression ? `(${progression} %)` : ''}</p>}
      {occupe === 'enregistrement' && <p className="mb-1 text-xs font-semibold text-rose-600">● Enregistrement… cliquez sur ■ pour arrêter et transcrire</p>}
      {occupe === 'transcription' && <p className="mb-1 text-xs text-sky-700">Patientez… transcription de la note vocale</p>}
      <div className="flex items-center gap-1.5">
        <button type="button" className={classeBouton} disabled={bloque} onClick={() => setEmojisOuverts((v) => !v)} title="Emojis" aria-label="Emojis" aria-expanded={emojisOuverts}><IcoEmoji /></button>
        <input ref={photoRef} type="file" accept="image/*" className="hidden" onChange={(e) => envoyerFichier(e.target.files?.[0], true)} />
        <button type="button" className={classeBouton} disabled={bloque || occupe === 'enregistrement'} onClick={() => photoRef.current?.click()} title="Envoyer une photo (galerie, appareil photo)" aria-label="Envoyer une photo"><IcoPhoto /></button>
        {captureDisponible && (
          <button type="button" className={classeBouton} disabled={bloque || occupe === 'enregistrement'} onClick={capturerEcran} title="Capture d'écran : montrer mon écran au support" aria-label="Capture d'écran"><IcoCapture /></button>
        )}
        <input ref={tromboneRef} type="file" accept={TYPES_TROMBONE} className="hidden" onChange={(e) => envoyerFichier(e.target.files?.[0], false)} />
        <button type="button" className={classeBouton} disabled={bloque || occupe === 'enregistrement'} onClick={() => tromboneRef.current?.click()} title="Joindre un document ou une vidéo (PDF, Word, Excel, PowerPoint, texte, CSV, MP4)" aria-label="Joindre un document ou une vidéo"><IcoTrombone /></button>
        <button type="button" disabled={bloque} onClick={basculerMicro}
                className={occupe === 'enregistrement' ? 'inline-flex h-8 w-8 animate-pulse items-center justify-center rounded-lg bg-rose-500 text-white' : classeBouton}
                title={occupe === 'enregistrement' ? 'Arrêter et transcrire' : 'Note vocale (transcription automatique)'}
                aria-label={occupe === 'enregistrement' ? 'Arrêter et transcrire' : 'Note vocale'}>
          {occupe === 'enregistrement' ? <IcoStop /> : <IcoMicro />}
        </button>
      </div>
      {/* Choix d'un emoji : ajouté à la fin du message en cours */}
      {emojisOuverts && (
        <div className="absolute bottom-full left-2 z-10 mb-1 grid w-[248px] grid-cols-8 gap-0.5 rounded-xl bg-white p-2 shadow-xl ring-1 ring-slate-200" role="listbox" aria-label="Emojis">
          {EMOJIS.map((e) => (
            <button key={e} type="button" className="rounded-md p-1 text-lg leading-none hover:bg-slate-100" onClick={() => { setTexte((t) => `${t || ''}${e}`); setEmojisOuverts(false) }}>{e}</button>
          ))}
        </div>
      )}
    </div>
  )
}

// ============================================================================
// Pièce jointe d'un message : photo (miniature, agrandie au clic), vidéo, document (téléchargé au clic)
// Le fichier est lu avec le jeton de connexion (jamais d'adresse publique).
// ============================================================================
export function PieceJointe({ api, media, moi = false }) {
  const [url, setUrl] = useState('')
  const [grand, setGrand] = useState(false)
  const [erreur, setErreur] = useState(false)
  const image = media.genre === 'image'
  const video = media.genre === 'video'

  // Lecture du fichier : tout de suite pour une photo, au clic pour une vidéo ou un document
  const charger = async () => {
    if (url) return url
    try {
      const r = await api.get(`/support-sawali/media/${media.id}`, { responseType: 'blob', timeout: 120000 })
      const u = URL.createObjectURL(r.data)
      setUrl(u)
      return u
    } catch { setErreur(true); return '' }
  }
  useEffect(() => { if (image) charger() }, [media.id])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])

  // Document : téléchargé sous son nom d'origine
  const telecharger = async () => {
    const u = await charger()
    if (!u) return
    const a = document.createElement('a')
    a.href = u
    a.download = media.nom || 'document'
    document.body.appendChild(a); a.click(); a.remove()
  }

  if (erreur) return <p className="text-xs italic opacity-70">Fichier indisponible</p>
  if (image) {
    return (
      <>
        {url
          ? <button type="button" onClick={() => setGrand(true)} className="block" title="Agrandir" aria-label="Agrandir la photo"><img src={url} alt={media.nom || 'Photo'} className="max-h-48 rounded-lg object-cover" /></button>
          : <div className="h-24 w-32 animate-pulse rounded-lg bg-slate-200" aria-label="Chargement de la photo" />}
        {grand && (
          <div className="fixed inset-0 z-[1100] grid place-items-center bg-black/80 p-4" onClick={() => setGrand(false)} role="dialog" aria-label="Photo agrandie">
            <img src={url} alt={media.nom || 'Photo'} className="max-h-full max-w-full rounded-lg" />
          </div>
        )}
      </>
    )
  }
  if (video && url) return <video src={url} controls className="max-h-56 w-full rounded-lg" />
  return (
    <button type="button" onClick={video ? charger : telecharger}
            className={`flex max-w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs font-semibold ${moi ? 'bg-white/15 hover:bg-white/25' : 'bg-slate-100 hover:bg-slate-200'}`}>
      <span aria-hidden="true">{video ? '🎬' : '📄'}</span>
      <span className="truncate">{media.nom || (video ? 'Vidéo' : 'Document')}</span>
      <span className="shrink-0 opacity-70">{video ? '▶' : '⬇'}</span>
    </button>
  )
}
