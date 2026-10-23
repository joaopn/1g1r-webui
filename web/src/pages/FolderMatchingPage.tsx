import { useMutation } from "@tanstack/react-query";
import { Archive, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ApplyDialog } from "@/components/apply/ApplyDialog";
import { RunPanel } from "@/components/apply/RunPanel";
import { useRestore } from "@/components/apply/useRestore";
import { useSetAside } from "@/components/apply/useSetAside";
import { Box } from "@/components/Box";
import { DatOrderEditor } from "@/components/DatOrderEditor";
import { GamesTable } from "@/components/games/GamesTable";
import { RankingEditor } from "@/components/RankingEditor";
import { ScanPanel } from "@/components/ScanPanel";
import { StatCard } from "@/components/StatCard";
import { UnsupportedFiles } from "@/components/UnsupportedFiles";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { UnmatchedTools, useUnmatchedActions } from "@/components/unmatched/Unmatched";
import { ApiError, api, json } from "@/lib/api";
import { formatCount, formatFiles } from "@/lib/format";
import {
  invalidateFolder,
  keys,
  queryClient,
  useFolder,
  useFolderCard,
  useGames,
  useMeta,
  useSettingsData,
  useUnmatched,
} from "@/lib/queries";
import type { Game, Ranking, Version } from "@/lib/types";
import { FolderHeader } from "@/pages/FolderHeader";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

export function FolderMatchingPage() {
  const { label = "" } = useParams();
  const card = useFolderCard(label);
  const meta = useMeta();
  const folder = useFolder(label, meta.data?.ui.poll_interval_ms ?? false);
  const games = useGames(label);
  const settingsData = useSettingsData();
  const unmatchedFiles = useUnmatched(label);
  // What the apply dialog is open for: the whole folder (null) or one game.
  const [applying, setApplying] = useState<{ game: Game | null } | null>(null);
  const restore = useRestore(label);
  const unmatchedActions = useUnmatchedActions(label, meta.data);
  const setAside = useSetAside(label, meta.data);

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
  const unassign = useMutation({
    mutationFn: (version: Version) =>
      api(`/folders/${label}/assign`, json("PUT", { rel_path: version.rel_path, game_name: null })),
    onSuccess: (_, version) => {
      toast.success(`${version.rel_path} is unmatched again`);
      return invalidateFolder(label);
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
  const other = (f.summary.counts.other ?? 0) + (f.summary.counts.ignored ?? 0);
  const scanning = f.scan?.status === "running";
  // Files not in the target format yet: scanning and 1G1R wait for them (converted first).
  const waiting = f.summary.waiting ?? 0;
  const convertFirst = `Convert or discard first: ${formatFiles(waiting)} not in the target format (Conversion tab)`;
  // The DATs identifying this set, in order (switched-off ones left out).
  const dats = f.dat_order.filter((e) => e.on && e.dat);
  const lookupsOn = !!settingsData.data && settingsData.data.lookups.hasheous;
  const proposed = (games.data ?? []).reduce(
    (n, g) => n + g.versions.filter((v) => v.operation).length,
    0,
  );

  return (
    <div className="space-y-6">
      <FolderHeader folder={f} meta={meta.data} section="matching" card={card} />

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

      <ScanPanel
        label={label}
        kind="identify"
        scan={f.scan}
        lastScan={f.last_scan}
        title="Matching"
        blocked={waiting > 0 ? convertFirst : undefined}
        actions={
          f.dat_order.some((e) => e.dat) ? (
            <DatOrderEditor
              platform={f.platform}
              platformName={meta.data.platforms[f.platform]?.name ?? f.platform}
              entries={f.dat_order}
              own={f.dat_order_own}
            />
          ) : null
        }
      >
        {dats.length > 0 ? (
          <ol className="space-y-0.5">
            {dats.map((entry, index) => {
              const source = meta.data.dat_sources[entry.id];
              return (
                <li key={entry.id}>
                  <span className="font-medium">{dats.length > 1 ? `${index + 1}. ` : "DAT "}</span>
                  {entry.dat?.header_name}{" "}
                  <span className="text-muted-foreground">
                    · {entry.label} · {entry.dat?.version ?? "?"}
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
                </li>
              );
            })}
          </ol>
        ) : (
          <>
            <span className="font-medium">DAT</span>{" "}
            <span className="text-status-warn">none — add one in Settings → DATs</span>
          </>
        )}
      </ScanPanel>

      <UnsupportedFiles
        files={f.unsupported}
        folder={f}
        meta={meta.data}
        busy={scanning}
        onMove={setAside.move}
      />
      {(f.summary.unscanned ?? 0) > 0 ? (
        <p
          className="rounded-md border border-border bg-card px-3 py-2 text-muted-foreground text-sm"
          data-testid="unscanned"
        >
          Not scanned yet: {formatFiles(f.summary.unscanned ?? 0)}. Scan to identify them.
        </p>
      ) : null}
      {(f.summary.waiting ?? 0) > 0 ? (
        <p
          className="rounded-md border border-border bg-card px-3 py-2 text-muted-foreground text-sm"
          data-testid="waiting"
        >
          Not in the target format yet: {formatFiles(f.summary.waiting ?? 0)}. Convert them, or move
          what can't be converted to discarded/, on the{" "}
          <Link
            to={`/folders/${label}/conversion`}
            className="text-primary underline underline-offset-2"
          >
            Conversion tab
          </Link>
          ; scanning and 1G1R wait until none is left.
        </p>
      ) : null}
      {(f.summary.counts.other ?? 0) > 0 ? (
        <p className="flex items-center gap-2 rounded-md border border-status-warn px-3 py-2 text-sm text-status-warn">
          <TriangleAlert className="size-4" aria-hidden="true" />
          {f.summary.counts.other} file(s) here are not {meta.data.platforms[f.platform]?.name}{" "}
          ROMs. A folder must contain one platform only; they are listed below and never touched.
        </p>
      ) : null}

      <Box
        title="1G1R"
        actions={
          <>
            <RankingEditor
              meta={meta.data}
              ranking={f.ranking}
              isDefault={f.ranking_is_default}
              onSave={(value) => ranking.mutate(value)}
            />
            <Button
              disabled={proposed === 0 || scanning || waiting > 0}
              onClick={() => setApplying({ game: null })}
              title={
                waiting > 0
                  ? convertFirst
                  : proposed === 0
                    ? "No proposed moves"
                    : "Review every proposed move, then apply"
              }
            >
              <Archive className="size-4" aria-hidden="true" />
              Apply 1G1R{proposed > 0 ? ` (${formatFiles(proposed)})` : ""}
            </Button>
          </>
        }
      >
        <p className="text-muted-foreground">
          {proposed > 0
            ? `${formatFiles(proposed)} proposed to move to discarded/; review the games below, then apply.`
            : "No moves proposed."}
        </p>
      </Box>

      <RunPanel label={label} meta={meta.data} />

      <section className="space-y-3" aria-label="Games">
        {games.data ? (
          <GamesTable
            label={label}
            games={games.data}
            meta={meta.data}
            onKeep={(game, relPath) => keep.mutate({ game, relPath })}
            onLeave={(game, left) => leave.mutate({ game, left })}
            onUnassign={(version) => unassign.mutate(version)}
            onApplyGame={(game) => setApplying({ game })}
            convertFirst={f.convert_first}
            unmatched={
              unmatchedFiles.data
                ? {
                    files: unmatchedFiles.data,
                    busy: scanning,
                    onAssign: unmatchedActions.assign,
                    onMove: unmatchedActions.move,
                    tools: (files, selected, clear) => (
                      <UnmatchedTools
                        label={label}
                        files={files}
                        selected={selected}
                        lookupsOn={lookupsOn}
                        scanning={scanning}
                        onMove={unmatchedActions.move}
                        onMatchFirst={unmatchedActions.matchFirst}
                        onClearSelection={clear}
                      />
                    ),
                  }
                : undefined
            }
            onRestore={(target) =>
              restore.mutate(
                "game" in target
                  ? { group_key: target.game.key }
                  : { operation_ids: target.version.discarded ? [target.version.discarded] : [] },
              )
            }
          />
        ) : (
          <p className="text-muted-foreground">Loading games…</p>
        )}
      </section>

      {applying ? (
        <ApplyDialog
          label={label}
          groupKey={applying.game?.key ?? null}
          title={applying.game ? `Apply 1G1R to ${applying.game.name}` : `Apply 1G1R to ${label}`}
          meta={meta.data}
          open
          onOpenChange={(open) => {
            if (!open) setApplying(null);
          }}
        />
      ) : null}

      {unmatchedActions.dialog}
      {setAside.dialog}
    </div>
  );
}
