/*
  Lot 45 — petit sélecteur d'emojis pour la zone de saisie des conversations WhatsApp.
  Sans bibliothèque : une grille par catégorie ; un clic insère l'emoji (le parent le place à la position du curseur).
  Props : onChoisir(emoji)
*/
import React, { useEffect, useRef, useState } from "react";
import { Smile } from "lucide-react";
import { Button } from "@/components/ui/button";

const CATEGORIES = {
  "Visages": "😀 😁 😂 🤣 😊 😇 🙂 😉 😍 😘 😋 😎 🤗 🤔 😐 😴 😢 😭 😡 😱 🥳 🤝".split(" "),
  "Gestes": "👍 👎 👏 🙏 🙌 👋 👌 ✌️ 🤞 💪 👀 ✅ ❌ ⚠️ ❗ ❓ ➡️ ⬆️ ⬇️".split(" "),
  "Cœurs": "❤️ 🧡 💛 💚 💙 💜 🖤 🤍 💔 💯 ✨ 🌟 🔥 🎉 🎊 🎁".split(" "),
  "Bureau": "📄 📎 📁 📅 📆 📞 📱 💻 📧 📨 🧾 💰 💳 🏦 📈 📉 🔒 🔑 ⏰ ⌛".split(" "),
  "Divers": "🌍 🌞 🌙 ⭐ 🌱 🌳 🌧️ ☀️ 🚗 ✈️ 🏠 🏢 🍽️ ☕ 🎂 ⚽".split(" "),
};

export default function SelecteurEmojis({ onChoisir }) {
  const [ouvert, setOuvert] = useState(false);
  const [categorie, setCategorie] = useState("Visages");
  const boite = useRef(null);

  // Fermeture au clic en dehors
  useEffect(() => {
    if (!ouvert) return undefined;
    const dehors = (e) => { if (boite.current && !boite.current.contains(e.target)) setOuvert(false); };
    document.addEventListener("mousedown", dehors);
    return () => document.removeEventListener("mousedown", dehors);
  }, [ouvert]);

  return (
    <div className="relative" ref={boite}>
      <Button type="button" variant="outline" size="icon" onClick={() => setOuvert((v) => !v)} title="Emojis" aria-label="Emojis" data-testid="wa-inbox-emoji-btn">
        <Smile className="w-4 h-4" />
      </Button>
      {ouvert && (
        <div className="absolute bottom-full left-0 z-30 mb-2 w-72 max-w-[85vw] rounded-lg border bg-white p-2 shadow-lg" data-testid="wa-inbox-emoji-panneau">
          <div className="mb-1 flex flex-wrap gap-1">
            {Object.keys(CATEGORIES).map((c) => (
              <button key={c} type="button" onClick={() => setCategorie(c)}
                      className={`rounded px-2 py-0.5 text-xs ${c === categorie ? "bg-[#0F6B4A] text-white" : "bg-slate-100"}`}>{c}</button>
            ))}
          </div>
          <div className="grid max-h-40 grid-cols-8 gap-1 overflow-y-auto">
            {CATEGORIES[categorie].map((e) => (
              <button key={e} type="button" onClick={() => onChoisir(e)} className="rounded p-1 text-xl hover:bg-slate-100" aria-label={e}>{e}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
