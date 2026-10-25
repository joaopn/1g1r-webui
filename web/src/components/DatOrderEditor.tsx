import { useMutation } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ListOrdered } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ApiError, api, json } from "@/lib/api";
import { keys, queryClient } from "@/lib/queries";
import type { DatOrderEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

/** `on` as the platform's own switch: an entry off on every platform stays off whatever it is. */
const ownSwitches = (list: DatOrderEntry[]) => list.map((e) => ({ ...e, on: !e.own_off }));

/**
 * The order a platform's DATs and online lookups identify files in: each tries the files
 * the ones above it missed. Saved for every set of the platform; the next scan uses it.
 */
export function DatOrderEditor({
  platform,
  platformName,
  entries,
  own = false,
  compact = false,
}: {
  platform: string;
  platformName: string;
  entries: DatOrderEntry[];
  /** The platform has its own order: it can go back to the default one. */
  own?: boolean;
  /** Without the order on the button (a narrow table cell). */
  compact?: boolean;
}) {
  const [draft, setDraft] = useState(() => ownSwitches(entries));
  useEffect(() => setDraft(ownSwitches(entries)), [entries]);
  const save = useMutation({
    mutationFn: (reset: boolean) =>
      api(
        `/dats/${platform}/order`,
        json("PUT", {
          order: reset ? null : draft.map((e) => e.id),
          off: draft.filter((e) => !e.on).map((e) => e.id),
        }),
      ),
    onSuccess: () => {
      toast.success(`${platformName}: DAT order saved; scan to use it`);
      queryClient.invalidateQueries({ queryKey: keys.dats });
      queryClient.invalidateQueries({ queryKey: keys.folders });
      queryClient.invalidateQueries({ queryKey: ["folder"] });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const move = (index: number, by: number) => {
    const next = [...draft];
    const [item] = next.splice(index, 1);
    next.splice(index + by, 0, item);
    setDraft(next);
  };
  const toggle = (id: string) =>
    setDraft(draft.map((e) => (e.id === id ? { ...e, on: !e.on } : e)));
  const summary =
    entries
      .filter((e) => e.on)
      .map((e) => e.label)
      .join(" → ") || "nothing";

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size={compact ? "sm" : "default"} data-testid="dat-order-button">
          <ListOrdered className="size-4" aria-hidden="true" />
          DAT order
          {compact ? null : (
            <span className="hidden max-w-80 truncate text-muted-foreground xl:inline">
              · {summary}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96" aria-label={`DAT order for ${platformName}`}>
        <p className="mb-3 text-muted-foreground text-xs">
          Top to bottom: each tries the files the ones above it did not identify. Saved for every{" "}
          {platformName} set{own ? "" : ", in place of the default order"}; the next scan uses it.
          Add DATs in Settings → Platform DATs.
        </p>
        <ol className="space-y-1">
          {draft.map((entry, index) => (
            <li
              key={entry.id}
              className={cn(
                "flex items-center gap-2 rounded-md border border-border px-2 py-1 text-sm",
                (!entry.on || entry.global_off) && "border-dashed text-muted-foreground",
              )}
            >
              <span className="w-4 text-muted-foreground tabular-nums">{index + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate">{entry.label}</span>
                <span className="block truncate text-muted-foreground text-xs">
                  {entry.dat
                    ? `${entry.dat.header_name} · ${entry.dat.version ?? "?"}`
                    : "online lookup (switched on in Settings → Online lookups)"}
                </span>
              </span>
              <Button
                variant="ghost"
                size="icon-xs"
                disabled={index === 0}
                onClick={() => move(index, -1)}
                aria-label={`Move ${entry.label} up`}
              >
                <ArrowUp aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                disabled={index === draft.length - 1}
                onClick={() => move(index, 1)}
                aria-label={`Move ${entry.label} down`}
              >
                <ArrowDown aria-hidden="true" />
              </Button>
              {entry.global_off ? (
                <Link
                  to="/settings/dat-sources"
                  className="w-10 shrink-0 text-status-warn text-xs underline underline-offset-2"
                  title="Switched off for every platform in Settings → Which DATs to use?"
                >
                  off
                </Link>
              ) : (
                <label className="flex w-10 shrink-0 items-center gap-1.5 text-xs">
                  <input
                    type="checkbox"
                    className="size-3.5 accent-primary"
                    checked={entry.on}
                    onChange={() => toggle(entry.id)}
                    aria-label={`Use ${entry.label}`}
                  />
                  {entry.on ? "on" : "off"}
                </label>
              )}
            </li>
          ))}
        </ol>
        <div className="mt-4 flex justify-end gap-2">
          {own ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={save.isPending}
              onClick={() => save.mutate(true)}
              title="The configured order, every entry switched on here"
            >
              Back to the default order
            </Button>
          ) : null}
          <Button size="sm" disabled={save.isPending} onClick={() => save.mutate(false)}>
            Save order
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
