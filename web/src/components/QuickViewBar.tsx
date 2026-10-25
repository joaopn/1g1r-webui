import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";

export type ChipTone = "good" | "convert" | "match" | "unscanned" | "rename";
/** `note`: a few words after the count, e.g. the share of the view needing a look. */
export type QuickViewChip = {
  id: string;
  label: string;
  count: number;
  tone?: ChipTone;
  note?: string;
};

// Literal class names, so Tailwind generates them.
const TONES: Record<ChipTone, { idle: string; dot: string; active: string }> = {
  good: {
    idle: "border-status-good/60",
    dot: "bg-status-good",
    active: "border-status-good bg-status-good",
  },
  convert: {
    idle: "border-status-convert/60",
    dot: "bg-status-convert",
    active: "border-status-convert bg-status-convert",
  },
  match: {
    idle: "border-status-match/60",
    dot: "bg-status-match",
    active: "border-status-match bg-status-match",
  },
  unscanned: {
    idle: "border-status-unscanned/60",
    dot: "bg-status-unscanned",
    active: "border-status-unscanned bg-status-unscanned",
  },
  rename: {
    idle: "border-status-rename/60",
    dot: "bg-status-rename",
    active: "border-status-rename bg-status-rename",
  },
};

/** The horizontal bar of quick views above a table, each with its count: one at a time, or
 * several when `value` is a list (`onChange` then gets the view clicked, to toggle). */
export function QuickViewBar({
  name,
  views,
  value,
  onChange,
}: {
  name: string;
  views: QuickViewChip[];
  value: string | readonly string[];
  onChange: (view: string) => void;
}) {
  const multiple = typeof value !== "string";
  return (
    <fieldset className="flex flex-wrap gap-1.5" data-testid="quick-views">
      <legend className="sr-only">Show</legend>
      {views.map((view) => {
        const active = multiple ? value.includes(view.id) : view.id === value;
        const tone = view.tone ? TONES[view.tone] : null;
        return (
          <label
            key={view.id}
            className={cn(
              "inline-flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition-colors",
              "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
              active
                ? tone
                  ? cn(tone.active, "text-background")
                  : "border-primary bg-primary text-primary-foreground"
                : cn(
                    tone ? tone.idle : "border-border",
                    "bg-card hover:bg-accent hover:text-accent-foreground",
                  ),
            )}
            data-tone={view.tone}
          >
            <input
              type={multiple ? "checkbox" : "radio"}
              name={name}
              className="sr-only"
              value={view.id}
              checked={active}
              onChange={() => onChange(view.id)}
            />
            {tone && !active ? (
              <span className={cn("size-2 rounded-full", tone.dot)} aria-hidden="true" />
            ) : null}
            {view.label}
            <span
              className={cn(
                "text-xs tabular-nums",
                active
                  ? tone
                    ? "text-background/80"
                    : "text-primary-foreground/80"
                  : "text-muted-foreground",
              )}
            >
              {formatCount(view.count)}
              {view.note ? ` ${view.note}` : null}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}
