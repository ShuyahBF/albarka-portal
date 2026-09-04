import React, { useEffect, useMemo, useState } from "react";
import { Check, ChevronsUpDown, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { apiClient, extractError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

/**
 * Searchable client (tenant) selector.
 *
 * Loads `GET /api/clients` once, then filters locally.
 * `value` holds the selected user id (== tenant_id). `onChange(id)` fires
 * whenever the user picks a client.
 *
 * Props:
 *   - value: current tenant_id (string)
 *   - onChange: (id) => void
 *   - placeholder: fallback label when no value is set
 *   - disabled: read-only mode
 *   - testId: root data-testid (default "entity-select")
 */
export default function EntitySelect({
  value,
  onChange,
  placeholder = "Sélectionner un client…",
  disabled = false,
  testId = "entity-select",
}) {
  const [open, setOpen] = useState(false);
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const { data } = await apiClient.get("/clients");
        if (alive) setClients(data || []);
      } catch (err) {
        toast.error(extractError(err, "Impossible de charger la liste des clients"));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const selected = useMemo(
    () => clients.find((c) => c.id === value) || null,
    [clients, value]
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled || loading}
          className="w-full justify-between h-10 font-normal"
          data-testid={testId}
        >
          {loading ? (
            <span className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" /> Chargement…
            </span>
          ) : selected ? (
            <span className="truncate text-left">
              <span className="font-medium">{selected.full_name}</span>
              {selected.company && (
                <span className="text-muted-foreground"> — {selected.company}</span>
              )}
            </span>
          ) : (
            <span className="text-muted-foreground">{placeholder}</span>
          )}
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
        <Command>
          <CommandInput placeholder="Rechercher un client…" data-testid={`${testId}-search`} />
          <CommandList>
            <CommandEmpty>Aucun client trouvé.</CommandEmpty>
            <CommandGroup>
              {clients.map((c) => (
                <CommandItem
                  key={c.id}
                  value={`${c.full_name} ${c.company || ""} ${c.email || ""}`}
                  onSelect={() => {
                    onChange(c.id);
                    setOpen(false);
                  }}
                  data-testid={`${testId}-option-${c.id}`}
                >
                  <Check
                    className={`mr-2 h-4 w-4 ${
                      value === c.id ? "opacity-100" : "opacity-0"
                    }`}
                  />
                  <div className="flex flex-col">
                    <span className="font-medium">{c.full_name}</span>
                    <span className="text-xs text-muted-foreground">
                      {c.company || c.email || "—"}
                    </span>
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
