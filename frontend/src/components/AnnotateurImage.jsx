/*
  Lot 430 — ANNOTATION d'une image (capture d'écran…) avant de la joindre à une demande : flèche, rectangle, texte, crayon, quatre couleurs,
  annuler le dernier tracé, tout effacer. Tout se passe dans le navigateur (canvas) ; l'image annotée est recompressée en JPEG pour tenir dans la limite.
  Pointeur unique (souris, doigt, stylet). Chaque outil : pictogramme + légende (règle 15).
*/
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUpRight, Check, Pencil, Square, Trash2, Type, Undo2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PIECE_MAX_OCTETS, ESSAIS_COMPRESSION, dimensionsCible } from "@/lib/piecesJointes";

const COULEURS = [["#dc2626", "Rouge"], ["#2563eb", "Bleu"], ["#16a34a", "Vert"], ["#111827", "Noir"]];
const OUTILS = [["fleche", "Flèche", ArrowUpRight], ["rect", "Rectangle", Square], ["texte", "Texte", Type], ["crayon", "Crayon", Pencil]];

/** Dessine UN tracé sur le contexte (flèche avec pointe, rectangle, texte ou ligne libre). */
function tracer(ctx, t, epaisseur) {
  ctx.strokeStyle = t.couleur; ctx.fillStyle = t.couleur; ctx.lineWidth = epaisseur; ctx.lineCap = "round"; ctx.lineJoin = "round";
  if (t.type === "rect") { ctx.strokeRect(t.x1, t.y1, t.x2 - t.x1, t.y2 - t.y1); return; }
  if (t.type === "crayon") { ctx.beginPath(); t.points.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y))); ctx.stroke(); return; }
  if (t.type === "texte") { ctx.font = `bold ${epaisseur * 6}px sans-serif`; ctx.textBaseline = "top"; ctx.fillText(t.texte, t.x1, t.y1); return; }
  // flèche : trait + pointe à l'arrivée
  ctx.beginPath(); ctx.moveTo(t.x1, t.y1); ctx.lineTo(t.x2, t.y2); ctx.stroke();
  const angle = Math.atan2(t.y2 - t.y1, t.x2 - t.x1); const L = epaisseur * 5;
  ctx.beginPath(); ctx.moveTo(t.x2, t.y2);
  ctx.lineTo(t.x2 - L * Math.cos(angle - Math.PI / 6), t.y2 - L * Math.sin(angle - Math.PI / 6));
  ctx.lineTo(t.x2 - L * Math.cos(angle + Math.PI / 6), t.y2 - L * Math.sin(angle + Math.PI / 6)); ctx.closePath(); ctx.fill();
}

/** Canvas → JPEG qui tient dans la limite : essais de moins en moins fidèles (échelle, qualité). Rend un Blob, ou null si impossible. */
export async function canvasEnJpeg(canvas, maxOctets = PIECE_MAX_OCTETS) {
  for (const { echelle, qualite } of ESSAIS_COMPRESSION) {
    const c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(canvas.width * echelle)); c.height = Math.max(1, Math.round(canvas.height * echelle));
    const ctx = c.getContext("2d"); ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, c.width, c.height); ctx.drawImage(canvas, 0, 0, c.width, c.height);
    const blob = await new Promise((r) => c.toBlob(r, "image/jpeg", qualite));
    if (blob && blob.size <= maxOctets) return blob;
  }
  return null;
}

/** Fenêtre d'annotation. `fichier` : image (File ou Blob) ; `onValider(blob)` reçoit le JPEG annoté ; `onFermer()` abandonne. */
export default function AnnotateurImage({ fichier, onValider, onFermer }) {
  const toile = useRef(null);
  const image = useRef(null);
  const [outil, setOutil] = useState("fleche");
  const [couleur, setCouleur] = useState(COULEURS[0][0]);
  const [traces, setTraces] = useState([]);
  const [enCours, setEnCours] = useState(null);
  const [erreur, setErreur] = useState("");
  const [occupe, setOccupe] = useState(false);
  const epaisseur = useRef(4);

  const dessiner = useCallback((liste, provisoire) => {
    const c = toile.current; if (!c || !image.current) return;
    const ctx = c.getContext("2d");
    ctx.clearRect(0, 0, c.width, c.height); ctx.drawImage(image.current, 0, 0, c.width, c.height);
    [...liste, ...(provisoire ? [provisoire] : [])].forEach((t) => tracer(ctx, t, epaisseur.current));
  }, []);

  // Chargement de l'image dans le canvas (réduite à 1600 px au plus)
  useEffect(() => {
    if (!fichier) return undefined;
    const url = URL.createObjectURL(fichier); const img = new Image();
    img.onload = () => {
      image.current = img; const d = dimensionsCible(img.naturalWidth, img.naturalHeight, 1600);
      const c = toile.current; if (!c) return;
      c.width = d.largeur; c.height = d.hauteur; epaisseur.current = Math.max(3, Math.round(d.largeur / 300));
      dessiner([], null);
    };
    img.onerror = () => setErreur("Image illisible");
    img.src = url;
    return () => URL.revokeObjectURL(url);
  }, [fichier, dessiner]);

  useEffect(() => { dessiner(traces, enCours); }, [traces, enCours, dessiner]);

  // Position du pointeur dans le repère du canvas (le canvas est affiché à l'échelle de l'écran)
  const position = (e) => { const r = toile.current.getBoundingClientRect(); return { x: ((e.clientX - r.left) / r.width) * toile.current.width, y: ((e.clientY - r.top) / r.height) * toile.current.height }; };
  const debut = (e) => {
    e.preventDefault(); const p = position(e);
    if (outil === "texte") { const texte = window.prompt("Texte à écrire sur l'image :"); if (texte && texte.trim()) setTraces([...traces, { type: "texte", couleur, x1: p.x, y1: p.y, texte: texte.trim().slice(0, 80) }]); return; }
    toile.current.setPointerCapture?.(e.pointerId);
    setEnCours(outil === "crayon" ? { type: "crayon", couleur, points: [p] } : { type: outil, couleur, x1: p.x, y1: p.y, x2: p.x, y2: p.y });
  };
  const deplacer = (e) => { if (!enCours) return; const p = position(e); setEnCours(enCours.type === "crayon" ? { ...enCours, points: [...enCours.points, p] } : { ...enCours, x2: p.x, y2: p.y }); };
  const fin = () => { if (enCours) { setTraces([...traces, enCours]); setEnCours(null); } };

  const valider = async () => {
    setOccupe(true); setErreur("");
    const blob = await canvasEnJpeg(toile.current);
    setOccupe(false);
    if (!blob) { setErreur("Impossible de réduire cette image à 400 Ko : choisissez une image plus simple."); return; }
    onValider(blob);
  };

  return (
    <Dialog open onOpenChange={(o) => { if (!o && !occupe) onFermer(); }}>
      <DialogContent className="max-w-3xl max-h-[90dvh] overflow-y-auto" data-testid="annotateur-image">
        <DialogHeader><DialogTitle>Annoter l'image</DialogTitle></DialogHeader>
        <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Outils d'annotation">
          {OUTILS.map(([id, nom, Picto]) => (
            <Button key={id} size="sm" variant={outil === id ? "default" : "outline"} onClick={() => setOutil(id)} aria-pressed={outil === id} data-testid={`outil-${id}`}><Picto className="w-4 h-4 mr-1" aria-hidden="true" />{nom}</Button>
          ))}
          <span className="mx-1 h-6 w-px bg-border" />
          {COULEURS.map(([c, nom]) => (
            <button key={c} type="button" onClick={() => setCouleur(c)} aria-label={`Couleur ${nom}`} aria-pressed={couleur === c} title={nom}
              className={`h-7 w-7 rounded-full border-2 ${couleur === c ? "border-orange-500 ring-2 ring-orange-300" : "border-white shadow"}`} style={{ background: c }} />
          ))}
          <span className="mx-1 h-6 w-px bg-border" />
          <Button size="sm" variant="outline" disabled={traces.length === 0} onClick={() => setTraces(traces.slice(0, -1))} data-testid="annuler-trace"><Undo2 className="w-4 h-4 mr-1" aria-hidden="true" />Annuler le dernier</Button>
          <Button size="sm" variant="outline" disabled={traces.length === 0} onClick={() => setTraces([])}><Trash2 className="w-4 h-4 mr-1" aria-hidden="true" />Tout effacer</Button>
        </div>
        <div className="overflow-auto rounded border bg-slate-100">
          <canvas ref={toile} className="mx-auto block max-h-[60dvh] max-w-full touch-none cursor-crosshair" onPointerDown={debut} onPointerMove={deplacer} onPointerUp={fin} onPointerLeave={fin} data-testid="toile-annotation" />
        </div>
        {erreur && <p role="alert" className="text-sm font-semibold text-red-700">{erreur}</p>}
        <div className="flex justify-end gap-2">
          <Button onClick={valider} disabled={occupe} data-testid="valider-annotation"><Check className="w-4 h-4 mr-1" aria-hidden="true" />{occupe ? "Patientez…" : "Valider l'image"}</Button>
          <Button variant="outline" onClick={onFermer} disabled={occupe}><X className="w-4 h-4 mr-1" aria-hidden="true" />Annuler</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
