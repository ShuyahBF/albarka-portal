import * as React from "react"
import * as TabsPrimitive from "@radix-ui/react-tabs"

import { cn } from "@/lib/utils"

const Tabs = TabsPrimitive.Root

const TabsList = React.forwardRef(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      // Onglets soulignés (design SAWALI)
      "inline-flex h-auto items-center justify-start gap-2 border-b border-slate-200 bg-transparent p-0 text-slate-500 overflow-x-auto max-w-full",
      className
    )}
    {...props} />
))
TabsList.displayName = TabsPrimitive.List.displayName

const TabsTrigger = React.forwardRef(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      // `bg-background` (quasi blanc) sur `bg-muted` (quasi blanc aussi) : le
      // fond de l'onglet actif se distingue à peine du fond de la page —
      // filet rouge de secours pour marquer la sélection quel que soit le
      // thème (bordure transparente au repos pour ne pas décaler la taille).
      "inline-flex items-center justify-center gap-1.5 whitespace-nowrap border-b-2 border-transparent -mb-px px-3 py-2 text-sm transition hover:text-slate-900 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 data-[state=active]:border-primary data-[state=active]:text-primary data-[state=active]:font-semibold",
      className
    )}
    {...props} />
))
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName

const TabsContent = React.forwardRef(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
      className
    )}
    {...props} />
))
TabsContent.displayName = TabsPrimitive.Content.displayName

export { Tabs, TabsList, TabsTrigger, TabsContent }
