import { useMutation, useQuery } from "@tanstack/react-query";
import { Archive, Globe, ListChecks, RefreshCw, Search, Trash2, X } from "lucide-react";
import { type CSSProperties, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { GuardedDialog } from "@/components/apply/GuardedDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ApiError, api, json } from "@/lib/api";
import { formatFiles } from "@/lib/format";
import { invalidateFolder, keys, queryClient } from "@/lib/queries";
import type { LookupStatus, Meta, UnmatchedFile } from "@/lib/types";

const PERCENT = new Intl.NumberFormat("en-US", { style: "percent" });

const LOOKUP_TEXT: Record<LookupStatus, string> = {
  off: "lookups off",
  found: "found",
  "not found": "not found online",
  "other platform": "known for another platform",
  "not in the DAT": "known, not under a DAT name",
  error: "lookup failed",
  skipped: "not asked",
};

const LOOKUP_STYLE: Record<LookupStatus, string> = {
  off: "border-border text-muted-foreground",
  found: "border-status-good/60 text-status-good",
  "not found": "border-border text-muted-foreground",
  "other platform": "border-status-warn text-status-warn",
  "not in the DAT": "border-status-warn text-status-warn",
  error: "border-status-bad text-status-bad",
  skipped: "border-border text-muted-foreground",
};

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

/**
 * Actions on files nothing identified: assigning one to a DAT entry by hand (kept across
 * scans), and moving files out to discarded/ or deleting them, each reviewed in a dialog.
 */
export function useUnmatchedActions(label: string, meta: Meta | undefined) {
  // The files under review and whether they are deleted (guarded) or moved to discarded/.
  const [acting, setActing] = useState<{ relPaths: string[]; remove: boolean } | null>(null);
  // The assigned rows leave the table at once; the refetch afterwards brings them back as games.
  const assign = useMutation({
    mutationFn: (pairs: { relPath: string; game: string }[]) =>
      api(
        `/folders/${label}/assign-many`,
        json("PUT", {
          assignments: pairs.map((p) => ({ rel_path: p.relPath, game_name: p.game })),
        }),
      ),
    onMutate: (pairs) => {
      const gone = new Set(pairs.map((p) => p.relPath));
      queryClient.setQueryData<UnmatchedFile[]>(keys.unmatched(label), (files) =>
        files?.filter((f) => !gone.has(f.rel_path)),
      );
    },
    onSuccess: (_, pairs) => {
      toast.success(
        pairs.length === 1
          ? `Assigned to ${pairs[0].game}`
          : `Assigned ${formatFiles(pairs.length)}`,
      );
    },
    onError: (err) => toast.error(errorText(err)),
    onSettled: () => invalidateFolder(label),
  });
  const named = (relPaths: string[]) =>
    relPaths.length === 1 ? relPaths[0] : formatFiles(relPaths.length);
  const dialog =
    acting && meta ? (
      <GuardedDialog
        label={label}
        path="unmatched"
        body={{ rel_paths: acting.relPaths, delete: acting.remove }}
        title={
          acting.remove
            ? `Delete ${named(acting.relPaths)}`
            : `Move ${named(acting.relPaths)} to discarded/`
        }
        description={
          acting.remove
            ? "These files are deleted for good; nothing identified them, so check them first."
            : `These files move to ${meta.discarded_root}/${label}/manual/, and can be restored from the Discarded page.`
        }
        action={(n) => (acting.remove ? `Delete ${formatFiles(n)}` : `Move ${formatFiles(n)}`)}
        meta={meta}
        open
        onOpenChange={(open) => {
          if (!open) setActing(null);
        }}
      />
    ) : null;
  return {
    assign: (relPath: string, game: string) => assign.mutate([{ relPath, game }]),
    /** Assign each file to its first suggestion; files without one are left as they are. */
    matchFirst: (files: UnmatchedFile[]) => {
      const pairs = firstMatches(files);
      if (pairs.length > 0) assign.mutate(pairs);
    },
    /** Review moving the files to discarded/, or deleting them (remove). */
    move: (relPaths: string[], remove: boolean) => setActing({ relPaths, remove }),
    dialog,
  };
}

function firstMatches(files: UnmatchedFile[]) {
  return files.flatMap((f) =>
    f.suggestions.length > 0 ? [{ relPath: f.rel_path, game: f.suggestions[0].game_name }] : [],
  );
}

/**
 * Above the table in the Unmatched view: what these files are, and actions on the selected
 * rows, or on every row shown when none is selected. Match to 1st takes selected rows only.
 */
export function UnmatchedTools({
  label,
  files,
  selected,
  lookupsOn,
  scanning,
  onMove,
  onMatchFirst,
  onClearSelection,
}: {
  label: string;
  /** The unmatched files the table shows. */
  files: UnmatchedFile[];
  /** The ones of those the user selected. */
  selected: UnmatchedFile[];
  lookupsOn: boolean;
  scanning: boolean;
  onMove: (relPaths: string[], remove: boolean) => void;
  onMatchFirst: (files: UnmatchedFile[]) => void;
  onClearSelection: () => void;
}) {
  const retry = useMutation({
    mutationFn: () => api(`/folders/${label}/scan?refresh_lookups=true`, { method: "POST" }),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => toast.error(errorText(err)),
  });
  const target = selected.length > 0 ? selected : files;
  const relPaths = target.map((f) => f.rel_path);
  const matchable = firstMatches(selected).length;
  return (
    <div className="space-y-2 rounded-md border border-border bg-card px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-56 flex-1 text-muted-foreground text-xs">
          Nothing identified these files, so they are kept as they are. Select rows (shift-click for
          a range) to match them to their 1st match; open a row with its arrow for other names or
          the DAT search. Your choices are kept across scans.
        </p>
        <Button
          size="sm"
          disabled={scanning || matchable === 0}
          onClick={() => {
            onMatchFirst(selected);
            onClearSelection();
          }}
          title={
            selected.length === 0
              ? "Select rows first"
              : "Assign each selected file to its 1st match (rows without one stay)"
          }
        >
          <ListChecks className="size-3.5" aria-hidden="true" /> Match{" "}
          {matchable > 0 ? `${formatFiles(matchable)} ` : ""}to 1st
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={scanning || target.length === 0}
          onClick={() => onMove(relPaths, false)}
          title={`Review, then move the files ${selected.length > 0 ? "selected" : "shown"} to discarded/ (can be restored)`}
        >
          <Archive className="size-3.5" aria-hidden="true" /> Move {formatFiles(target.length)} to
          discarded/
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={scanning || target.length === 0}
          className="text-status-bad"
          onClick={() => onMove(relPaths, true)}
          title={`Review, then delete the files ${selected.length > 0 ? "selected" : "shown"} for good`}
        >
          <Trash2 className="size-3.5" aria-hidden="true" /> Delete {formatFiles(target.length)}
        </Button>
        {lookupsOn ? (
          <Button
            variant="outline"
            size="sm"
            disabled={scanning || retry.isPending || files.length === 0}
            onClick={() => retry.mutate()}
            title="Rescan, asking the online lookups again about files they did not know"
          >
            <RefreshCw className="size-3.5" aria-hidden="true" /> Look up again
          </Button>
        ) : (
          <Link
            to="/settings/lookups"
            className="inline-flex items-center gap-1 text-muted-foreground text-sm underline underline-offset-2"
          >
            <Globe className="size-3.5" aria-hidden="true" /> Online lookups are off
          </Link>
        )}
      </div>
      {selected.length > 0 ? (
        <p className="flex items-center gap-2 text-xs">
          {formatFiles(selected.length)} selected
          <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={onClearSelection}>
            <X className="size-3" aria-hidden="true" /> Clear selection
          </Button>
        </p>
      ) : null}
    </div>
  );
}

/** An unmatched file's row, opened: its hashes, what the lookups said, and the closest names. */
export function UnmatchedDetail({
  file,
  label,
  hashLength,
  busy,
  onAssign,
}: {
  file: UnmatchedFile;
  label: string;
  hashLength: number;
  busy: boolean;
  onAssign: (game: string) => void;
}) {
  return (
    <div className="space-y-1.5 text-sm" data-testid={`unmatched-${file.rel_path}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {file.hash ? (
          <code className="text-muted-foreground text-xs" title={`SHA1 ${file.hash.sha1}`}>
            CRC {file.hash.crc32} · SHA1 {file.hash.sha1.slice(0, hashLength)}
          </code>
        ) : null}
        <LookupBadge service="Hasheous" lookup={file.hasheous} />
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {file.suggestions.length > 0 ? (
          <span className="text-muted-foreground text-xs">Looks like</span>
        ) : (
          <span className="text-muted-foreground text-xs">No close DAT name.</span>
        )}
        {file.suggestions.map((s) => (
          <button
            key={s.game_name}
            type="button"
            disabled={busy}
            onClick={() => onAssign(s.game_name)}
            title={`Assign this file to ${s.game_name}`}
            className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-0.5 text-xs transition-colors hover:border-primary hover:bg-accent disabled:opacity-50"
          >
            {s.game_name}
            <span className="h-1 w-6 overflow-hidden rounded-full bg-muted" aria-hidden="true">
              <span
                className="block h-full w-[calc(var(--p)*100%)] rounded-full bg-primary"
                style={{ "--p": s.score } as CSSProperties}
              />
            </span>
            <span className="text-muted-foreground tabular-nums">{PERCENT.format(s.score)}</span>
          </button>
        ))}
        <DatSearch label={label} busy={busy} onAssign={onAssign} />
      </div>
    </div>
  );
}

function LookupBadge({ service, lookup }: { service: string; lookup: UnmatchedFile["hasheous"] }) {
  if (!lookup) return null;
  const detailShown = lookup.status === "skipped" || lookup.status === "not in the DAT";
  return (
    <Badge
      variant="outline"
      className={LOOKUP_STYLE[lookup.status]}
      title={lookup.detail || undefined}
    >
      {service}: {LOOKUP_TEXT[lookup.status]}
      {detailShown && lookup.detail ? ` (${lookup.detail})` : ""}
    </Badge>
  );
}

function DatSearch({
  label,
  busy,
  onAssign,
}: {
  label: string;
  busy: boolean;
  onAssign: (game: string) => void;
}) {
  const [q, setQ] = useState("");
  const results = useQuery({
    queryKey: ["dat-search", label, q],
    queryFn: () =>
      api<string[]>(`/folders/${label}/dat-search?${new URLSearchParams({ q }).toString()}`),
    enabled: q.trim().length > 0,
  });
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-6 px-2 text-xs">
          <Search className="size-3" aria-hidden="true" /> Search the DAT
        </Button>
      </PopoverTrigger>
      <PopoverContent anchored align="end" className="w-80" aria-label="Search the DAT">
        <Input
          aria-label="DAT entry"
          placeholder="Type part of a game name"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
        {/* A fixed height, so the panel is measured whole when it opens and stays on screen. */}
        <ul className="mt-2 h-64 overflow-y-auto">
          {(results.data ?? []).map((name) => (
            <li key={name}>
              <button
                type="button"
                disabled={busy}
                onClick={() => onAssign(name)}
                className="w-full rounded-sm px-2 py-1 text-left text-sm hover:bg-accent"
              >
                {name}
              </button>
            </li>
          ))}
          {q.trim() && results.data?.length === 0 ? (
            <li className="px-2 py-1 text-muted-foreground text-sm">No DAT entry matches.</li>
          ) : null}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

/** An unmatched row's 1st match cell: the closest DAT name and how close it is. */
export function FirstMatch({ file }: { file: UnmatchedFile }) {
  const first = file.suggestions[0];
  if (!first) return <span className="text-muted-foreground text-xs">no close name</span>;
  return (
    <span
      className="flex min-w-0 items-center gap-1.5"
      title={`${first.game_name} (${PERCENT.format(first.score)})`}
    >
      <span className="min-w-0 truncate">{first.game_name}</span>
      <span className="h-1.5 w-8 shrink-0 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <span
          className="block h-full w-[calc(var(--p)*100%)] rounded-full bg-primary"
          style={{ "--p": first.score } as CSSProperties}
        />
      </span>
      <span className="shrink-0 text-muted-foreground text-xs tabular-nums">
        {PERCENT.format(first.score)}
      </span>
    </span>
  );
}
