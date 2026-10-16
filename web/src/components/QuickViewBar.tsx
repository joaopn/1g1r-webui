import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";

export type QuickViewChip = { id: string; label: string; count: number };

/** The horizontal bar of quick views above a table: one at a time, each with its count. */
export function QuickViewBar({
  name,
  views,
  value,
  onChange,
}: {
  name: string;
  views: QuickViewChip[];
  value: string;
  onChange: (view: string) => void;
}) {
  return (
    <fieldset className="flex flex-wrap gap-1.5" data-testid="quick-views">
      <legend className="sr-only">Show</legend>
      {views.map((view) => {
        const active = view.id === value;
        return (
          <label
            key={view.id}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition-colors",
              "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card hover:bg-accent hover:text-accent-foreground",
            )}
          >
            <input
              type="radio"
              name={name}
              className="sr-only"
              value={view.id}
              checked={active}
              onChange={() => onChange(view.id)}
            />
            {view.label}
            <span
              className={cn(
                "text-xs tabular-nums",
                active ? "text-primary-foreground/80" : "text-muted-foreground",
              )}
            >
              {formatCount(view.count)}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}
