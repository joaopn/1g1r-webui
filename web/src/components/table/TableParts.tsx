import { ArrowDown, ArrowUp, Columns3, ListFilter } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { formatCount } from "@/lib/format";
import type { ColumnSize, Meta } from "@/lib/types";
import { useDragWidth } from "@/lib/useDragWidth";
import { cn } from "@/lib/utils";

/** The parts every table shares: sortable, resizable headers; the column and filter menus. */

export function HeaderCell({
  id,
  label,
  sortable,
  size,
  width,
  meta,
  active,
  order,
  onSort,
  onResize,
  className,
}: {
  id: string;
  label: string;
  sortable: boolean;
  size: ColumnSize;
  width: number;
  meta: Meta;
  active: boolean;
  order: "asc" | "desc";
  onSort: (id: string) => void;
  onResize: (id: string, rem: number | null) => void;
  className?: string;
}) {
  const drag = useDragWidth({
    width,
    min: size.min,
    max: size.max,
    step: meta.ui.resize_step_rem,
    shiftMultiplier: meta.ui.resize_shift_multiplier,
    defaultPx: meta.ui.rem_fallback_px,
    onChange: (rem) => onResize(id, rem),
    onReset: () => onResize(id, null),
  });
  return (
    <div className={cn("relative min-w-0", className)} data-testid={`header-${id}`}>
      {sortable ? (
        <button
          type="button"
          onClick={() => onSort(id)}
          data-testid={`sort-${id}`}
          className={cn(
            "inline-flex max-w-full items-center gap-1 uppercase tracking-wide hover:text-foreground",
            active && "text-foreground",
          )}
        >
          <span className="truncate">{label}</span>
          {active ? (
            order === "asc" ? (
              <ArrowUp className="size-3 shrink-0" aria-label="ascending" />
            ) : (
              <ArrowDown className="size-3 shrink-0" aria-label="descending" />
            )
          ) : null}
        </button>
      ) : (
        <span className="block truncate">{label}</span>
      )}
      {/* biome-ignore lint/a11y/useSemanticElements: an <hr> cannot take focus; a focusable separator is the ARIA splitter. */}
      <span
        role="separator"
        aria-orientation="vertical"
        aria-label={`Resize the ${label || id} column`}
        aria-valuenow={width}
        aria-valuemin={size.min}
        aria-valuemax={size.max}
        tabIndex={0}
        title="Drag to resize, double-click to reset"
        data-testid={`resize-${id}`}
        className={cn(
          "-right-2 absolute top-0 z-[1] flex h-full w-3 cursor-col-resize touch-none select-none justify-center",
          "after:h-full after:w-px after:bg-border hover:after:bg-foreground/40",
          "focus-visible:outline-none focus-visible:after:w-0.5 focus-visible:after:bg-ring",
        )}
        {...drag}
      />
    </div>
  );
}

export function ColumnChooser({
  columns,
  visible,
  onChange,
  widthsChanged,
  onResetWidths,
}: {
  columns: { id: string; label: string }[];
  visible: string[];
  onChange: (next: string[]) => void;
  widthsChanged: boolean;
  onResetWidths: () => void;
}) {
  const shown = new Set(visible);
  const toggle = (id: string) => {
    const next = shown.has(id)
      ? visible.filter((v) => v !== id)
      : columns.map((c) => c.id).filter((v) => shown.has(v) || v === id);
    if (next.length > 0) onChange(next);
  };
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" data-testid="columns-button">
          <Columns3 className="size-3.5" aria-hidden="true" /> Columns
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-52" aria-label="Columns">
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-muted-foreground text-xs">Columns</legend>
          {columns.map((column) => (
            <label key={column.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-3.5 accent-primary"
                checked={shown.has(column.id)}
                disabled={shown.has(column.id) && visible.length <= 1}
                onChange={() => toggle(column.id)}
                data-testid={`column-${column.id}`}
              />
              {column.label}
            </label>
          ))}
        </fieldset>
        <Button
          variant="ghost"
          size="sm"
          className="mt-3 w-full"
          disabled={!widthsChanged}
          onClick={onResetWidths}
        >
          Reset widths
        </Button>
      </PopoverContent>
    </Popover>
  );
}

/** One group of checkboxes in the Filters menu: none checked means no filter. */
export type FilterGroup = {
  id: string;
  label: string;
  options: { value: string; label: string; count: number }[];
  selected: string[];
};

export function FilterMenu({
  groups,
  onChange,
  onClear,
  extra,
  extraActive = 0,
}: {
  groups: FilterGroup[];
  onChange: (groupId: string, selected: string[]) => void;
  onClear: () => void;
  /** Filters of other kinds (a checkbox, a select), below the groups. */
  extra?: React.ReactNode;
  /** How many of those are set. */
  extraActive?: number;
}) {
  const active = groups.filter((g) => g.selected.length > 0).length + extraActive;
  const toggle = (group: FilterGroup, value: string) =>
    onChange(
      group.id,
      group.selected.includes(value)
        ? group.selected.filter((v) => v !== value)
        : [...group.selected, value],
    );
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" data-testid="filters-button">
          <ListFilter className="size-3.5" aria-hidden="true" /> Filters
          {active > 0 ? <Badge className="ml-1">{active}</Badge> : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 space-y-3" aria-label="Filters">
        {groups.map((group) => (
          <fieldset key={group.id} className="space-y-1.5">
            <legend className="mb-1 text-muted-foreground text-xs">{group.label}</legend>
            {group.options.map((option) => (
              <label key={option.value} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-3.5 accent-primary"
                  checked={group.selected.includes(option.value)}
                  onChange={() => toggle(group, option.value)}
                  data-testid={`filter-${group.id}-${option.value}`}
                />
                <span className="flex-1">{option.label}</span>
                <span className="text-muted-foreground text-xs tabular-nums">
                  {formatCount(option.count)}
                </span>
              </label>
            ))}
          </fieldset>
        ))}
        {extra}
        <Button
          variant="ghost"
          size="sm"
          className="w-full"
          disabled={active === 0}
          onClick={onClear}
        >
          Clear filters
        </Button>
      </PopoverContent>
    </Popover>
  );
}
