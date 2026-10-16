import { useMutation } from "@tanstack/react-query";
import { RefreshCw, TriangleAlert } from "lucide-react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { GamesTable } from "@/components/games/GamesTable";
import { RankingEditor } from "@/components/RankingEditor";
import { StatCard } from "@/components/StatCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError, api, json } from "@/lib/api";
import { formatBytes, formatCount, formatWhen } from "@/lib/format";
import { invalidateFolder, keys, queryClient, useFolder, useGames, useMeta } from "@/lib/queries";
import type { Game, Ranking } from "@/lib/types";
import { FolderHeader } from "@/pages/FolderHeader";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

export function FolderMatchingPage() {
  const { label = "" } = useParams();
  const meta = useMeta();
  const folder = useFolder(label, meta.data?.ui.poll_interval_ms ?? false);
  const games = useGames(label);

  const scan = useMutation({
    mutationFn: () => api(`/folders/${label}/scan`, { method: "POST" }),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => toast.error(errorText(err)),
  });
  const updateGame = (game: Game) =>
    queryClient.setQueryData<Game[]>(keys.games(label), (current) =>
      current?.map((g) => (g.key === game.key ? game : g)),
    );
  const keep = useMutation({
    mutationFn: ({ game, relPath }: { game: Game; relPath: string | null }) =>
      api<Game>(`/folders/${label}/keep`, json("PUT", { group_key: game.key, rel_path: relPath })),
    onSuccess: (game) => {
      updateGame(game);
      queryClient.invalidateQueries({ queryKey: keys.folders });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const leave = useMutation({
    mutationFn: ({ game, left }: { game: Game; left: boolean }) =>
      api<Game>(`/folders/${label}/leave`, json("PUT", { group_key: game.key, left })),
    onSuccess: (game) => {
      updateGame(game);
      queryClient.invalidateQueries({ queryKey: keys.folders });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const ranking = useMutation({
    mutationFn: (value: Ranking | null) =>
      api(`/folders/${label}/ranking`, json("PUT", { ranking: value })),
    onSuccess: () => {
      toast.success("Ranking saved");
      return invalidateFolder(label);
    },
    onError: (err) => toast.error(errorText(err)),
  });

  if (folder.error) return <p className="text-status-bad">{errorText(folder.error)}</p>;
  if (!meta.data || !folder.data) return <p className="text-muted-foreground">Loading…</p>;
  const f = folder.data;
  const ui = meta.data.ui;
  const running = f.scan?.status === "running";
  const source = f.dat ? meta.data.dat_sources[f.dat.source] : null;
  const other = (f.summary.counts.other ?? 0) + (f.summary.counts.ignored ?? 0);

  return (
    <div className="space-y-6">
      <FolderHeader folder={f} meta={meta.data} section="Matching & 1G1R" />

      <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
        <div className="space-y-1 text-sm">
          <div>
            <span className="font-medium">DAT</span>{" "}
            {f.dat ? (
              <>
                {f.dat.header_name}{" "}
                <span className="text-muted-foreground">
                  · {source?.label} · {f.dat.version ?? "?"}
                </span>{" "}
                {source?.identification_only ? (
                  <Badge
                    variant="outline"
                    className="border-status-warn text-status-warn"
                    title="No parent/clone data: versions are grouped from Retool's clone lists and DAT names"
                  >
                    identification only
                  </Badge>
                ) : null}
              </>
            ) : (
              <span className="text-status-warn">none — add one in Settings → DATs</span>
            )}
          </div>
          <div className="text-muted-foreground">
            {!f.scan ? (
              "Not scanned yet."
            ) : running ? (
              `Scanning since ${formatWhen(f.scan.started_at)}…`
            ) : f.scan.status === "done" ? (
              `Last scan ${formatWhen(f.scan.finished_at)}: ${f.scan.message}.`
            ) : (
              <span className="text-status-bad">
                Last scan failed ({formatWhen(f.scan.finished_at)}): {f.scan.message}
              </span>
            )}
          </div>
        </div>
        <Button onClick={() => scan.mutate()} disabled={running || scan.isPending}>
          <RefreshCw className={running ? "size-4 animate-spin" : "size-4"} aria-hidden="true" />
          {f.scan ? "Scan again" : "Scan folder"}
        </Button>
      </section>

      {f.summary.roms > 0 ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard value={formatCount(f.summary.roms)} label="ROM files" />
          <StatCard value={formatCount(f.summary.identified)} label="identified" />
          <StatCard
            value={formatCount(f.summary.unmatched)}
            label="unmatched"
            attention={f.summary.unmatched > 0}
          />
          <StatCard value={formatCount(other)} label="other files" />
        </div>
      ) : null}
      {(f.summary.counts.other ?? 0) > 0 ? (
        <p className="flex items-center gap-2 rounded-md border border-status-warn px-3 py-2 text-sm text-status-warn">
          <TriangleAlert className="size-4" aria-hidden="true" />
          {f.summary.counts.other} file(s) here are not {meta.data.platforms[f.platform]?.name}{" "}
          ROMs. A folder must contain one platform only; they are listed below and never touched.
        </p>
      ) : null}

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold text-lg">Games</h2>
          <RankingEditor
            meta={meta.data}
            ranking={f.ranking}
            isDefault={f.ranking_is_default}
            onSave={(value) => ranking.mutate(value)}
          />
        </div>
        {games.data ? (
          <GamesTable
            label={label}
            games={games.data}
            meta={meta.data}
            onKeep={(game, relPath) => keep.mutate({ game, relPath })}
            onLeave={(game, left) => leave.mutate({ game, left })}
          />
        ) : (
          <p className="text-muted-foreground">Loading games…</p>
        )}
      </section>

      <details className="rounded-lg border border-border bg-card">
        <summary className="cursor-pointer px-4 py-3 font-medium">
          Unmatched content ({formatCount(f.unmatched.length)})
        </summary>
        <div className="border-border border-t px-4 py-3 text-sm">
          {f.unmatched.length === 0 ? (
            <p className="text-muted-foreground">Every ROM file was identified.</p>
          ) : (
            <ul className="space-y-1">
              {f.unmatched.map((file) => (
                <li key={file.rel_path} className="flex justify-between gap-4">
                  <span className="truncate">{file.rel_path}</span>
                  <span className="shrink-0 text-muted-foreground tabular-nums">
                    {formatBytes(file.size, ui.byte_unit_base, ui.byte_units)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-muted-foreground text-xs">
            Online lookups (Hasheous, ScreenScraper) and manual assignment come in a later build.
            These files are kept as they are.
          </p>
        </div>
      </details>
      {f.others.length > 0 ? (
        <details className="rounded-lg border border-border bg-card">
          <summary className="cursor-pointer px-4 py-3 font-medium">
            Other files ({formatCount(f.others.length)})
          </summary>
          <ul className="space-y-1 border-border border-t px-4 py-3 text-sm">
            {f.others.map((file) => (
              <li key={file.rel_path} className="flex justify-between gap-4">
                <span className="truncate">{file.rel_path}</span>
                <span className="shrink-0 text-muted-foreground">
                  {file.kind === "ignored" ? "ignored filename" : "not a ROM of this platform"}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
