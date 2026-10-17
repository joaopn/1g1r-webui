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
import { formatBytes, formatCount, formatFiles } from "@/lib/format";
import { invalidateFolder, useUnmatched } from "@/lib/queries";
import type { LookupStatus, Meta, UnmatchedFile } from "@/lib/types";

const PERCENT = new Intl.NumberFormat("en-US", { style: "percent" });

const LOOKUP_TEXT: Record<LookupStatus, string> = {
  off: "lookups off",
  found: "found",
  "not found": "not found online",
  "other platform": "known for another platform",
  error: "lookup failed",
  skipped: "not asked",
};

const LOOKUP_STYLE: Record<LookupStatus, string> = {
  off: "border-border text-muted-foreground",
  found: "border-status-good/60 text-status-good",
  "not found": "border-border text-muted-foreground",
  "other platform": "border-status-warn text-status-warn",
  error: "border-status-bad text-status-bad",
  skipped: "border-border text-muted-foreground",
};

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

/**
 * Files nothing identified: what Hasheous said, the closest DAT names, and assigning a
 * file to a DAT entry by hand (kept across scans).
 */
export function UnmatchedSection({
  label,
  meta,
  hasheousOn,
  scanning,
}: {
  label: string;
  meta: Meta;
  hasheousOn: boolean;
  scanning: boolean;
}) {
  const files = useUnmatched(label);
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
  const retry = useMutation({
    mutationFn: () => api(`/folders/${label}/scan?refresh_lookups=true`, { method: "POST" }),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => toast.error(errorText(err)),
  });
  const rows = files.data ?? [];
  const formatSize = (value: number) =>
    formatBytes(value, meta.ui.byte_unit_base, meta.ui.byte_units);

  return (
    <section className="space-y-3" aria-labelledby="unmatched-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="unmatched-heading" className="font-semibold text-lg">
          Unmatched content{" "}
          <span className="font-normal text-muted-foreground">({formatCount(rows.length)})</span>
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          {rows.length > 0 ? (
            <>
              <Button
                variant="outline"
                size="sm"
                disabled={scanning}
                onClick={() => setActing({ relPaths: rows.map((r) => r.rel_path), remove: false })}
                title="Review, then move every unmatched file to discarded/ (can be restored)"
              >
                <Archive className="size-3.5" aria-hidden="true" /> Move all to discarded/
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={scanning}
                className="text-status-bad"
                onClick={() => setActing({ relPaths: rows.map((r) => r.rel_path), remove: true })}
                title="Review, then delete every unmatched file for good"
              >
                <Trash2 className="size-3.5" aria-hidden="true" /> Delete all
              </Button>
            </>
          ) : null}
          {hasheousOn ? (
            <Button
              variant="outline"
              size="sm"
              disabled={scanning || retry.isPending || rows.length === 0}
              onClick={() => retry.mutate()}
              title="Rescan, asking Hasheous again about files it did not know"
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
      <p className="text-muted-foreground text-xs">
        Nothing identified these files, so they are kept as they are. Click a suggestion, or search
        the DAT, to tell the app what a file is; your choice is kept across scans. Or move a file
        out to discarded/ (it can be restored), or delete it for good.
      </p>
      {rows.length === 0 ? (
        <p className="rounded-lg border border-border bg-card px-4 py-3 text-muted-foreground text-sm">
          Every ROM file was identified.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {rows.map((file) => (
            <UnmatchedRow
              key={file.rel_path}
              file={file}
              label={label}
              hashLength={meta.ui.hash_display_length}
              formatSize={formatSize}
              busy={assign.isPending || scanning}
              onAssign={(game) => assign.mutate({ relPath: file.rel_path, game })}
              onMove={(remove) => setActing({ relPaths: [file.rel_path], remove })}
            />
          ))}
        </ul>
      )}
      {acting ? (
        <GuardedDialog
          label={label}
          path="unmatched"
          body={{ rel_paths: acting.relPaths, delete: acting.remove }}
          title={
            acting.remove
              ? `Delete ${acting.relPaths.length === 1 ? acting.relPaths[0] : formatFiles(acting.relPaths.length)}`
              : `Move ${acting.relPaths.length === 1 ? acting.relPaths[0] : formatFiles(acting.relPaths.length)} to discarded/`
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
      ) : null}
    </section>
  );
}

function UnmatchedRow({
  file,
  label,
  hashLength,
  formatSize,
  busy,
  onAssign,
  onMove,
}: {
  file: UnmatchedFile;
  label: string;
  hashLength: number;
  formatSize: (value: number) => string;
  busy: boolean;
  onAssign: (game: string) => void;
  /** Review moving the file to discarded/, or deleting it (true). */
  onMove: (remove: boolean) => void;
}) {
  const lookup = file.hasheous;
  return (
    <li className="space-y-2 px-4 py-3 text-sm" data-testid={`unmatched-${file.rel_path}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="min-w-0 flex-1 truncate font-medium" title={file.rel_path}>
          {file.rel_path}
        </span>
        <span className="text-muted-foreground tabular-nums">{formatSize(file.size)}</span>
        {file.hash ? (
          <code className="text-muted-foreground text-xs" title={`SHA1 ${file.hash.sha1}`}>
            CRC {file.hash.crc32} · SHA1 {file.hash.sha1.slice(0, hashLength)}
          </code>
        ) : null}
        {lookup ? (
          <Badge
            variant="outline"
            className={LOOKUP_STYLE[lookup.status]}
            title={lookup.detail || undefined}
          >
            Hasheous: {LOOKUP_TEXT[lookup.status]}
            {lookup.status === "skipped" && lookup.detail ? ` (${lookup.detail})` : ""}
          </Badge>
        ) : null}
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
        <span className="ml-auto flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon-xs"
            disabled={busy}
            onClick={() => onMove(false)}
            title="Move to discarded/ (can be restored)"
            className="text-status-warn"
          >
            <Archive className="size-3.5" aria-hidden="true" />
            <span className="sr-only">Move {file.rel_path} to discarded</span>
          </Button>
          <Button
            variant="ghost"
            size="icon-xs"
            disabled={busy}
            onClick={() => onMove(true)}
            title="Delete for good"
            className="text-status-bad"
          >
            <Trash2 className="size-3.5" aria-hidden="true" />
            <span className="sr-only">Delete {file.rel_path}</span>
          </Button>
        </span>
      </div>
    </li>
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
      <PopoverContent align="start" className="w-80" aria-label="Search the DAT">
        <Input
          aria-label="DAT entry"
          placeholder="Type part of a game name"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
        <ul className="mt-2 max-h-64 overflow-y-auto">
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
