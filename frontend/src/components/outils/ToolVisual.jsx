/*
  Outils Numériques (lot 9) — visuel d'un outil : image envoyée par
  l'administrateur (lue avec le jeton de connexion) ou, à défaut, l'une des
  icônes prédéfinies (logiciel, PDF, tableur, archive, application mobile, vidéo).
*/
import React, { useEffect, useState } from "react";
import { AppWindow, FileText, FileSpreadsheet, Archive, Smartphone, Video } from "lucide-react";
import { apiClient } from "@/lib/api";

// Icônes prédéfinies : clé enregistrée côté serveur -> icône, libellé, couleurs
export const PRESET_ICONS = {
  logiciel: { icon: AppWindow, label: "Logiciel", cls: "bg-emerald-50 text-[#0F6B4A]" },
  pdf: { icon: FileText, label: "Document PDF", cls: "bg-rose-50 text-rose-600" },
  tableur: { icon: FileSpreadsheet, label: "Tableur", cls: "bg-green-50 text-green-700" },
  archive: { icon: Archive, label: "Archive (ZIP…)", cls: "bg-amber-50 text-amber-700" },
  mobile: { icon: Smartphone, label: "Application mobile", cls: "bg-sky-50 text-sky-700" },
  video: { icon: Video, label: "Vidéo", cls: "bg-violet-50 text-violet-700" },
};

// size : côté du carré en pixels (96 px par défaut, « taille moyenne »)
export default function ToolVisual({ tool, size = 96 }) {
  const [src, setSrc] = useState(null);

  // Image envoyée : chargée en blob (la route exige la connexion)
  useEffect(() => {
    if (!tool?.has_image) { setSrc(null); return undefined; }
    let alive = true;
    let objectUrl = null;
    apiClient.get(`/outils-numeriques/${tool.id}/image`, { params: { v: tool.image_rev }, responseType: "blob" })
      .then((res) => {
        objectUrl = URL.createObjectURL(res.data);
        if (alive) setSrc(objectUrl);
      })
      .catch(() => { if (alive) setSrc(null); });
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [tool?.id, tool?.has_image, tool?.image_rev]);

  const box = { width: size, height: size };
  if (src) {
    return <img src={src} alt={tool.caption} style={box} className="object-contain rounded-xl" draggable={false} />;
  }
  // Icône prédéfinie (logiciel par défaut)
  const preset = PRESET_ICONS[tool?.icon] || PRESET_ICONS.logiciel;
  const Icon = preset.icon;
  return (
    <div style={box} className={`rounded-xl flex items-center justify-center ${preset.cls}`}>
      <Icon style={{ width: size * 0.5, height: size * 0.5 }} />
    </div>
  );
}
