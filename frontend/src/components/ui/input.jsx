import * as React from "react"

import { Eye, EyeOff } from "lucide-react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef(({ className, type, sansOeil = false, ...props }, ref) => {
  // Règle 22 (16/11/2026) : tout champ de type « password » porte un pictogramme œil (afficher / masquer) ; masqué par défaut.
  // `sansOeil` : pour un champ qui gère déjà son propre œil (évite un doublon).
  const [voir, setVoir] = React.useState(false)
  const secret = type === "password" && !sansOeil
  const champ = (
    <input
      type={secret ? (voir ? "text" : "password") : type}
      className={cn(
        // Champ compact (design SAWALI) : bord gris, focus aux couleurs du site
        "flex h-9 w-full rounded-lg border border-slate-300 bg-white px-3 py-1 text-base text-slate-900 transition file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-slate-400 focus-visible:outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/15 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:opacity-60 md:text-sm",
        secret && "pr-10",
        className
      )}
      ref={ref}
      {...props} />
  )
  if (!secret) return champ
  return (
    <div className="relative">
      {champ}
      <button type="button" onClick={() => setVoir((v) => !v)} tabIndex={-1}
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-slate-400 hover:text-slate-700"
        aria-label={voir ? "Masquer la saisie" : "Afficher la saisie"} title={voir ? "Masquer la saisie" : "Afficher la saisie"}>
        {voir ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  )
})
Input.displayName = "Input"

export { Input }
