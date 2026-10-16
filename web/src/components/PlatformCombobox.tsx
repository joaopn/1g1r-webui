import { Check, ChevronsUpDown } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { PlatformIcon } from "@/components/PlatformIcon";
import type { Platform } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * A text field that lists the supported platforms and narrows them as you type (name, short
 * label or id). Arrow keys move, Enter picks, Escape closes. Closed, it shows the chosen
 * platform with its badge.
 */
export function PlatformCombobox({
  id,
  platforms,
  value,
  onChange,
  iconWidthRem,
}: {
  id: string;
  platforms: [string, Platform][];
  value: string;
  onChange: (id: string) => void;
  iconWidthRem?: number;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const listRef = useRef<HTMLDivElement>(null);
  const selected = platforms.find(([pid]) => pid === value)?.[1];

  const needle = query.trim().toLowerCase();
  const matches = platforms.filter(
    ([pid, p]) =>
      !needle ||
      p.name.toLowerCase().includes(needle) ||
      p.short.toLowerCase().includes(needle) ||
      pid.includes(needle),
  );
  const current = Math.min(active, matches.length - 1);

  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector("[data-active]")?.scrollIntoView?.({ block: "nearest" });
  });

  const show = (next: boolean) => {
    setOpen(next);
    setQuery("");
    setActive(
      Math.max(
        0,
        platforms.findIndex(([pid]) => pid === value),
      ),
    );
  };
  const choose = (pid: string) => {
    onChange(pid);
    setOpen(false);
    setQuery("");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) return show(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((current + step + matches.length) % Math.max(1, matches.length));
    } else if (event.key === "Enter" && open) {
      event.preventDefault();
      if (matches[current]) choose(matches[current][0]);
    } else if (event.key === "Escape" && open) {
      event.stopPropagation();
      setOpen(false);
    }
  };

  const badge = !open && selected;
  const inset = { paddingLeft: `calc(${iconWidthRem ?? 0}rem + 1rem)` } as CSSProperties;

  return (
    <div className="relative">
      {badge ? (
        <PlatformIcon
          platform={selected}
          widthRem={iconWidthRem}
          className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2"
        />
      ) : null}
      <input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && matches[current] ? `${listId}-${current}` : undefined}
        autoComplete="off"
        placeholder="Type to search platforms"
        className="h-9 w-full rounded-md border border-input bg-background pr-8 pl-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        style={badge ? inset : undefined}
        value={open ? query : (selected?.name ?? "")}
        onFocus={() => show(true)}
        onClick={() => !open && show(true)}
        onBlur={() => setOpen(false)}
        onChange={(event) => {
          setOpen(true);
          setQuery(event.target.value);
          setActive(0);
        }}
        onKeyDown={onKeyDown}
      />
      <ChevronsUpDown
        className="-translate-y-1/2 pointer-events-none absolute top-1/2 right-2.5 size-4 text-muted-foreground"
        aria-hidden="true"
      />
      {open ? (
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label="Platforms"
          className="absolute top-full right-0 left-0 z-50 mt-1 max-h-64 overflow-y-auto rounded-md border border-border bg-popover py-1 text-popover-foreground shadow-md"
        >
          {matches.map(([pid, p], index) => (
            // biome-ignore lint/a11y/useKeyWithClickEvents: the combobox input handles the keys.
            <div
              key={pid}
              id={`${listId}-${index}`}
              role="option"
              tabIndex={-1}
              aria-selected={pid === value}
              data-active={index === current ? "" : undefined}
              className={cn(
                "flex cursor-pointer items-center gap-2 px-2 py-1.5 text-sm",
                index === current && "bg-accent text-accent-foreground",
              )}
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActive(index)}
              onClick={() => choose(pid)}
            >
              <PlatformIcon platform={p} widthRem={iconWidthRem} />
              <span className="flex-1 truncate">{p.name}</span>
              {pid === value ? <Check className="size-4 text-primary" aria-hidden="true" /> : null}
            </div>
          ))}
          {matches.length === 0 ? (
            <p className="px-3 py-1.5 text-muted-foreground text-sm">No supported platform</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
