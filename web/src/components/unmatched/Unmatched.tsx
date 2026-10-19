import { useMutation, useQuery } from "@tanstack/react-query";
import { Archive, Globe, RefreshCw, Search, Trash2 } from "lucide-react";
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
import { invalidateFolder } from "@/lib/queries";
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
  const assign = useMutation({
    mutationFn: ({ relPath, game }: { relPath: string; game: string }) =>
      api(`/folders/${label}/assign`, json("PUT", { rel_path: relPath, game_name: game })),
    onSuccess: (_, { game }) => {
      toast.success(`Assigned to ${game}`);
      return invalidateFolder(label);
    },
    onError: (err) => toast.error(errorText(err)),
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
    assign: (relPath: string, game: string) => assign.mutate({ relPath, game }),
    assigning: assign.isPending,
    /** Review moving the files to discarded/, or deleting them (remove). */
    move: (relPaths: string[], remove: boolean) => setActing({ relPaths, remove }),
    dialog,
  };
}

/** Above the table in the Unmatched view: what these files are, and actions on all shown. */
export function UnmatchedTools({
  label,
  files,
  lookupsOn,
  scanning,
  onMove,
}: {
  label: string;
  /** The unmatched files the table shows. */
  files: UnmatchedFile[];
  lookupsOn: boolean;
  scanning: boolean;
  onMove: (relPaths: string[], remove: boolean) => void;
}) {
  const retry = useMutation({
    mutationFn: () => api(`/folders/${label}/scan?refresh_lookups=true`, { method: "POST" }),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => toast.error(errorText(err)),
  });
  const relPaths = files.map((f) => f.rel_path);
  return (
    <div className="space-y-2 rounded-md border border-border bg-card px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="min-w-56 flex-1 text-muted-foreground text-xs">
          Nothing identified these files, so they are kept as they are. Open a row and click a
          suggestion, or search the DAT, to tell the app what the file is; your choice is kept
          across scans.
        </p>
        <Button
          variant="outline"
          size="sm"
          disabled={scanning || files.length === 0}
          onClick={() => onMove(relPaths, false)}
          title="Review, then move the files shown to discarded/ (can be restored)"
        >
          <Archive className="size-3.5" aria-hidden="true" /> Move {formatFiles(files.length)} to
          discarded/
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={scanning || files.length === 0}
          className="text-status-bad"
          onClick={() => onMove(relPaths, true)}
          title="Review, then delete the files shown for good"
        >
          <Trash2 className="size-3.5" aria-hidden="true" /> Delete {formatFiles(files.length)}
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
