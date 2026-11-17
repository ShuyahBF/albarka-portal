/*
  Lot 430 — PIÈCES JOINTES d'une demande à SAWALI : choisir des images (captures…) ou des PDF, annoter les images, retirer.
  Les images sont réduites et recompressées en JPEG (400 Ko au plus) ; un PDF doit déjà tenir dans 400 Ko. 5 pièces au plus.
  `pieces` : [{ id, nom, type, taille, data (base64) }] ; `onChange(liste)`. Chaque action : pictogramme + légende (règle 15).
*/
import React, { useRef, useState } from "react";
import { toast } from "sonner";
import { FileText, Paperclip, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import AnnotateurImage, { canvasEnJpeg } from "@/components/AnnotateurImage";
import { ACCEPT, PIECES_MAX, PIECE_MAX_OCTETS, TYPES_IMAGES, base64DeDataUrl, dimensionsCible, formaterTaille, octetsDeBase64, refuserFichier } from "@/lib/piecesJointes";

const lireEnDataUrl = (blob) => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(blob); });

/** Image (File ou Blob) → pièce JPEG qui tient dans la limite ; null si impossible. */
async function imageEnPiece(fichier, nom) {
  const url = URL.createObjectURL(fichier);
  try {
    const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
    const d = dimensionsCible(img.naturalWidth, img.naturalHeight, 1600);
    const c = document.createElement("canvas"); c.width = d.largeur; c.height = d.hauteur; c.getContext("2d").drawImage(img, 0, 0, d.largeur, d.hauteur);
    const blob = await canvasEnJpeg(c);
    if (!blob) return null;
    const data = base64DeDataUrl(await lireEnDataUrl(blob));
    return { id: `p-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, nom: `${nom.replace(/\.[^.]+$/, "")}.jpg`, type: "image/jpeg", taille: octetsDeBase64(data), data };
  } finally { URL.revokeObjectURL(url); }
}

export default function PiecesJointes({ pieces, onChange, desactive = false }) {
  const entree = useRef(null);
  const [annotation, setAnnotation] = useState(null);       // { index, fichier } : image en cours d'annotation
  const [occupe, setOccupe] = useState(false);

  const ajouter = async (e) => {
    const fichiers = Array.from(e.target.files || []); e.target.value = "";
    let liste = [...pieces];
    setOccupe(true);
    for (const f of fichiers) {
      const refus = refuserFichier(f, liste.length);
      if (refus) { toast.error(refus); continue; }
      try {
        if (TYPES_IMAGES.includes(f.type)) {
          const p = await imageEnPiece(f, f.name);
          if (!p) { toast.error(`« ${f.name} » : impossible de la réduire à ${PIECE_MAX_OCTETS / 1024} Ko`); continue; }
          liste = [...liste, p];
        } else {
          const data = base64DeDataUrl(await lireEnDataUrl(f));
          liste = [...liste, { id: `p-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, nom: f.name, type: f.type, taille: octetsDeBase64(data), data }];
        }
      } catch { toast.error(`« ${f.name} » : fichier illisible`); }
    }
    setOccupe(false); onChange(liste);
  };

  // Annotation : on repart de l'image déjà réduite, puis on remplace la pièce par la version annotée
  const annoter = (i) => {
    const p = pieces[i];
    const octets = Uint8Array.from(atob(p.data), (c) => c.charCodeAt(0));
    setAnnotation({ index: i, fichier: new Blob([octets], { type: p.type }) });
  };
  const validerAnnotation = async (blob) => {
    const data = base64DeDataUrl(await lireEnDataUrl(blob));
    const nouvelle = pieces.map((p, i) => (i === annotation.index ? { ...p, data, type: "image/jpeg", taille: octetsDeBase64(data), nom: p.nom.replace(/(-annotee)?\.[^.]+$/, "-annotee.jpg") } : p));
    setAnnotation(null); onChange(nouvelle); toast.success("Image annotée");
  };

  return (
    <div className="space-y-2" data-testid="pieces-jointes">
      <div className="flex flex-wrap items-center gap-2">
        <input ref={entree} type="file" multiple accept={ACCEPT} className="sr-only" onChange={ajouter} data-testid="entree-pieces" aria-label="Choisir des fichiers à joindre" />
        <Button type="button" variant="outline" size="sm" disabled={desactive || occupe || pieces.length >= PIECES_MAX} onClick={() => entree.current?.click()}>
          <Paperclip className="w-4 h-4 mr-1" aria-hidden="true" />{occupe ? "Traitement…" : "Joindre des fichiers"}</Button>
        <span className="text-xs text-muted-foreground">{pieces.length}/{PIECES_MAX} · images (réduites à {PIECE_MAX_OCTETS / 1024} Ko) ou PDF de {PIECE_MAX_OCTETS / 1024} Ko au plus</span>
      </div>
      {pieces.length > 0 && (
        <ul className="space-y-1">
          {pieces.map((p, i) => (
            <li key={p.id} className="flex items-center gap-2 rounded border bg-white p-1.5 text-sm" data-testid={`piece-${i}`}>
              {p.type.startsWith("image/") ? <img src={`data:${p.type};base64,${p.data}`} alt={`Aperçu de ${p.nom}`} className="h-10 w-10 shrink-0 rounded object-cover" /> : <FileText className="h-10 w-10 shrink-0 p-2 text-red-700" aria-hidden="true" />}
              <span className="min-w-0 flex-1 truncate" title={p.nom}>{p.nom}</span>
              <span className="text-xs tabular-nums text-muted-foreground">{formaterTaille(p.taille)}</span>
              {p.type.startsWith("image/") && <Button type="button" size="sm" variant="outline" disabled={desactive} onClick={() => annoter(i)}><Pencil className="w-4 h-4 mr-1" aria-hidden="true" />Annoter</Button>}
              <Button type="button" size="sm" variant="ghost" className="text-red-700" disabled={desactive} onClick={() => onChange(pieces.filter((_, k) => k !== i))} aria-label={`Retirer ${p.nom}`}><Trash2 className="w-4 h-4 mr-1" aria-hidden="true" />Retirer</Button>
            </li>
          ))}
        </ul>
      )}
      {annotation && <AnnotateurImage fichier={annotation.fichier} onValider={validerAnnotation} onFermer={() => setAnnotation(null)} />}
    </div>
  );
}
