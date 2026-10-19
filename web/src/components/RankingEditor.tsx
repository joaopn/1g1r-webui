import { ArrowDown, ArrowUp, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Meta, Ranking } from "@/lib/types";
import { cn } from "@/lib/utils";

const split = (text: string) =>
  text
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);

/**
 * The folder's ranking: which criteria pick the version to keep, in which order. Off
 * criteria are listed after the on ones; ties stay undecided, by design.
 */
export function RankingEditor({
  meta,
  ranking,
  isDefault,
  onSave,
}: {
  meta: Meta;
  ranking: Ranking;
  isDefault: boolean;
  onSave: (ranking: Ranking | null) => void;
}) {
  const [draft, setDraft] = useState(ranking);
  const [regions, setRegions] = useState(ranking.regions.join(", "));
  const [languages, setLanguages] = useState(ranking.languages.join(", "));
  useEffect(() => {
    setDraft(ranking);
    setRegions(ranking.regions.join(", "));
    setLanguages(ranking.languages.join(", "));
  }, [ranking]);

  const labels = meta.ranking.labels;
  const off = meta.ranking.criteria.filter((c) => !draft.criteria.includes(c));
  const move = (index: number, by: number) => {
    const next = [...draft.criteria];
    const [item] = next.splice(index, 1);
    next.splice(index + by, 0, item);
    setDraft({ ...draft, criteria: next });
  };
  const summary = ranking.criteria.map((c) => labels[c]).join(" → ") || "no criteria";

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" data-testid="ranking-button">
          <SlidersHorizontal className="size-3.5" aria-hidden="true" />
          Ranking
          <span className="hidden max-w-80 truncate text-muted-foreground lg:inline">
            · {summary}
            {isDefault ? " (default)" : ""}
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96" aria-label="Ranking for this folder">
        <p className="mb-3 text-muted-foreground text-xs">
          Applied top to bottom. When the criteria that are on cannot separate two versions, the
          game stays <em>undecided</em> and you pick by clicking a version. There is no alphabetical
          tiebreak.
        </p>
        <ol className="space-y-1">
          {draft.criteria.map((c, index) => (
            <li
              key={c}
              className="flex items-center gap-2 rounded-md border border-border px-2 py-1 text-sm"
            >
              <span className="w-4 text-muted-foreground tabular-nums">{index + 1}</span>
              <span className="flex-1">{labels[c]}</span>
              <Button
                variant="ghost"
                size="icon-xs"
                disabled={index === 0}
                onClick={() => move(index, -1)}
                aria-label={`Move ${labels[c]} up`}
              >
                <ArrowUp aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                disabled={index === draft.criteria.length - 1}
                onClick={() => move(index, 1)}
                aria-label={`Move ${labels[c]} down`}
              >
                <ArrowDown aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                size="xs"
                onClick={() =>
                  setDraft({ ...draft, criteria: draft.criteria.filter((x) => x !== c) })
                }
              >
                off
              </Button>
            </li>
          ))}
          {off.map((c) => (
            <li
              key={c}
              className={cn(
                "flex items-center gap-2 rounded-md border border-dashed border-border px-2 py-1 text-muted-foreground text-sm",
              )}
            >
              <span className="w-4" />
              <span className="flex-1">{labels[c]}</span>
              <Button
                variant="ghost"
                size="xs"
                onClick={() => setDraft({ ...draft, criteria: [...draft.criteria, c] })}
              >
                on
              </Button>
            </li>
          ))}
        </ol>
        <div className="mt-3 space-y-2">
          <Label htmlFor="ranking-regions">Region priority</Label>
          <Input
            id="ranking-regions"
            value={regions}
            onChange={(e) => setRegions(e.target.value)}
          />
          <Label htmlFor="ranking-languages">Language priority</Label>
          <Input
            id="ranking-languages"
            value={languages}
            onChange={(e) => setLanguages(e.target.value)}
          />
          <Label htmlFor="ranking-multi">A release listing several regions counts as</Label>
          <select
            id="ranking-multi"
            className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm"
            value={draft.multi_region}
            onChange={(e) =>
              setDraft({ ...draft, multi_region: e.target.value as Ranking["multi_region"] })
            }
          >
            <option value="best">its best-ranked region</option>
            <option value="first">its first region (like RomM)</option>
          </select>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          {!isDefault ? (
            <Button variant="ghost" size="sm" onClick={() => onSave(null)}>
              Back to default
            </Button>
          ) : null}
          <Button
            size="sm"
            onClick={() =>
              onSave({ ...draft, regions: split(regions), languages: split(languages) })
            }
          >
            Save ranking
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
