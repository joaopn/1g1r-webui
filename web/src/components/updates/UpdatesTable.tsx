import { ArchiveRestore, Check, CornerDownRight } from "lucide-react";
import { useMemo } from "react";
import { flagTone } from "@/components/games/columns";
import {
  type DataColumn,
  DataTable,
  type RowGroup,
  type RowView,
} from "@/components/table/DataTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatBytes, formatCount } from "@/lib/format";
import type { Meta, UpdateGame, UpdateRow } from "@/lib/types";
import { cn } from "@/lib/utils";

type Row = UpdateRow & { name: string };

const STATUS_WORDS: Record<UpdateRow["status"], string> = {
  newest: "newest, kept",
  older: "older → discard",
  kept: "older, you keep it",
  "version unknown": "version unknown, kept",
  "left alone": "left alone",
  discarded: "in discarded/",
  dlc: "DLC, kept",
};

const STATUS_TONES: Record<UpdateRow["status"], string> = {
  newest: "font-medium text-status-good",
  older: "text-status-warn",
  kept: "text-status-good",
  "version unknown": "text-muted-foreground",
  "left alone": "text-muted-foreground",
  discarded: "text-muted-foreground",
  dlc: "text-status-good",
};

const VIEWS: RowView<Row>[] = [
  { id: "all", label: "All", test: () => true },
  { id: "proposed", label: "To discard", test: (r) => r.status === "older" },
  { id: "kept", label: "Older kept", test: (r) => r.status === "kept" },
  { id: "unknown", label: "Version unknown", test: (r) => r.status === "version unknown" },
  { id: "newer", label: "Newer released", test: (r) => r.newer },
  { id: "dlc", label: "DLC", test: (r) => r.role === "dlc" },
  { id: "discarded", label: "Discarded", test: (r) => r.status === "discarded" },
];

const plural = (n: number, word: string) => `${formatCount(n)} ${word}${n === 1 ? "" : "s"}`;

/** What a game's row says in the Status column, and its colour. */
/** A game's colour: an update to discard (yellow), else behind titledb's newest update
 * (blue), else on it (green); none when that cannot be told (no titledb). */
function gameTone(g: UpdateGame): string {
  if (g.to_discard > 0) return "text-status-warn";
  if (g.newer) return "text-status-info";
  return g.latest ? "text-status-good" : "";
}

/** What a game's row says in the Status column, in the game's colour. */
function gameStatus(g: UpdateGame): { text: string; tone: string } {
  const tone = gameTone(g);
  if (g.to_discard > 0) return { text: `${formatCount(g.to_discard)} older → discard`, tone };
  if (g.newer) return { text: "newer released", tone };
  if (g.updates > 0) return { text: g.latest ? "latest update" : "newest kept", tone };
  if (g.dlc > 0) return { text: "DLC kept", tone };
  return { text: "no update", tone: tone || "text-muted-foreground" };
}

const newerTitle = (g: UpdateGame) =>
  g.newer
    ? `titledb knows a newer update: update ${g.latest_release}${g.latest_date ? `, ${g.latest_date}` : ""}`
    : undefined;

/** The set's games, each a row holding its updates (newest first, the server's order) and
 * DLC, closed until clicked. Older updates are proposed for discarded/ unless kept, and a
 * discarded one can be restored. */
export function UpdatesTable({
  updates,
  games,
  meta,
  busy,
  onKeep,
  onRestore,
}: {
  updates: UpdateRow[];
  games: UpdateGame[];
  meta: Meta;
  busy: boolean;
  onKeep: (relPath: string, keep: boolean) => void;
  onRestore: (operationId: number) => void;
}) {
  const rows = useMemo<Row[]>(
    () => updates.map((u) => ({ ...u, name: u.rel_path.split("/").pop() ?? u.rel_path })),
    [updates],
  );
  const bytes = (size: number) => formatBytes(size, meta.ui.byte_unit_base, meta.ui.byte_units);
  const group: RowGroup<Row, UpdateGame> = {
    groups: games,
    groupKey: (g) => g.group_key,
    key: (r) => r.group_key,
    name: (g) => g.game,
    noun: "games",
    search: (g, needle) => g.game.toLocaleLowerCase().includes(needle),
    cell: (g, id) => {
      if (id === "game")
        return (
          <span className={cn("font-medium", gameTone(g))}>
            {g.game}
            {g.display_version ? <span className="font-normal"> ({g.display_version})</span> : null}
          </span>
        );
      if (id === "name")
        return (
          <span className="text-muted-foreground text-xs">
            {[
              ...(g.updates ? [plural(g.updates, "update")] : []),
              ...(g.dlc ? [`${formatCount(g.dlc)} DLC`] : []),
            ].join(" · ")}
          </span>
        );
      if (id === "latest" && g.latest_release !== null)
        return (
          <span className={cn("tabular-nums", g.newer && "font-medium text-status-info")}>
            {g.latest_release}
          </span>
        );
      if (id === "size" && g.size > 0)
        return <span className="text-muted-foreground tabular-nums">{bytes(g.size)}</span>;
      if (id === "status") {
        const { text, tone } = gameStatus(g);
        return <span className={tone}>{text}</span>;
      }
      return null;
    },
    title: (g, id) => (id === "game" || id === "status" ? newerTitle(g) : undefined),
    sortValue: (g, id) => {
      if (id === "game") return g.game.toLowerCase();
      if (id === "size") return g.size;
      if (id === "status") return gameStatus(g).text;
      if (id === "latest") return g.latest_release ?? -1;
      return undefined;
    },
    testId: (g) => `updates-game-${g.group_key}`,
    // Games with an update to discard start open.
    opens: (g) => g.to_discard > 0,
  };
  const columns = useMemo<DataColumn<Row>[]>(
    () => [
      {
        id: "game",
        label: "Game",
        sortValue: (r) => r.game.toLowerCase(),
        // The game's row heads them; its updates and DLC point to it.
        render: () => (
          <CornerDownRight
            className="ml-5 inline size-3.5 text-muted-foreground"
            aria-hidden="true"
          />
        ),
        title: (r) => r.game,
      },
      {
        id: "name",
        label: "File name",
        sortValue: (r) => r.name.toLowerCase(),
        render: (r) => r.name,
        title: (r) => r.rel_path,
      },
      {
        id: "release",
        label: "Update",
        sortValue: (r) => r.release ?? -1,
        render: (r) =>
          r.role === "dlc" ? (
            <span className="text-muted-foreground">DLC</span>
          ) : r.release === null ? (
            <span className="text-muted-foreground">unknown</span>
          ) : (
            <span className="tabular-nums">{r.release}</span>
          ),
      },
      {
        id: "latest",
        label: "Latest",
        sortValue: (r) => r.latest_release ?? -1,
        render: (r) =>
          r.latest_release === null ? (
            <span className="text-muted-foreground">–</span>
          ) : (
            <span className={cn("tabular-nums", r.newer && "font-medium text-status-info")}>
              {r.latest_release}
            </span>
          ),
        title: (r) =>
          r.latest_version === null
            ? "titledb knows no update of this game (or titledb is not downloaded)"
            : `The newest update titledb knows: v${r.latest_version}${
                r.latest_date ? `, released ${r.latest_date}` : ""
              }`,
      },
      {
        id: "display_version",
        label: "Version",
        sortValue: (r) => (r.role === "dlc" ? "" : (r.display_version ?? "")),
        render: (r) =>
          r.role === "dlc" ? (
            <span className="text-muted-foreground">DLC</span>
          ) : (
            (r.display_version ?? <span className="text-muted-foreground">–</span>)
          ),
        title: (r) => (r.role === "dlc" || r.display_version ? undefined : "read with prod.keys"),
      },
      {
        id: "version",
        label: "Version ID",
        sortValue: (r) => r.version ?? -1,
        render: (r) => (
          <span className="text-muted-foreground tabular-nums">
            {r.version === null ? "" : `v${r.version}`}
          </span>
        ),
      },
      {
        id: "title_id",
        label: "Title ID",
        sortValue: (r) => r.title_id,
        render: (r) => <code className="text-xs">{r.title_id}</code>,
      },
      {
        id: "size",
        label: "Size",
        className: "text-right",
        sortValue: (r) => r.size ?? 0,
        render: (r) => (
          <span className="text-muted-foreground tabular-nums">
            {r.size === null ? "" : formatBytes(r.size, meta.ui.byte_unit_base, meta.ui.byte_units)}
          </span>
        ),
      },
      {
        id: "status",
        label: "Status",
        sortValue: (r) => STATUS_WORDS[r.status],
        render: (r) => <span className={STATUS_TONES[r.status]}>{STATUS_WORDS[r.status]}</span>,
        title: (r) => r.reason,
      },
      {
        id: "notes",
        label: "Flags",
        sortValue: (r) => r.notes.join(", "),
        render: (r) =>
          r.notes.map((note) => (
            <Badge key={note} variant="outline" className={cn("mr-1 font-normal", flagTone(note))}>
              {note}
            </Badge>
          )),
        title: (r) => r.notes.join(", ") || undefined,
      },
    ],
    [meta],
  );
  const actions = (r: Row) => {
    if (r.status === "older" || r.status === "kept") {
      const kept = r.status === "kept";
      return (
        <Button
          variant={kept ? "secondary" : "outline"}
          size="xs"
          disabled={busy}
          aria-pressed={kept}
          aria-label={`Keep ${r.rel_path}`}
          onClick={() => onKeep(r.rel_path, !kept)}
        >
          {kept ? <Check aria-hidden="true" /> : null}
          Keep
        </Button>
      );
    }
    if (r.status === "discarded" && r.discarded !== null) {
      const id = r.discarded;
      return (
        <Button
          variant="outline"
          size="xs"
          disabled={busy}
          aria-label={`Restore ${r.rel_path}`}
          onClick={() => onRestore(id)}
        >
          <ArchiveRestore aria-hidden="true" />
          Restore
        </Button>
      );
    }
    return null;
  };
  return (
    <DataTable
      name="updates"
      label="Updates & DLC"
      noun="updates and DLC"
      rows={rows}
      rowKey={(r) => r.rel_path}
      rowTestId={(r) => `update-${r.rel_path}`}
      columns={columns}
      sizes={meta.ui.updates_columns}
      defaultColumns={meta.ui.updates_columns_default}
      views={VIEWS}
      group={group}
      search={(r, needle) =>
        r.rel_path.toLocaleLowerCase().includes(needle) ||
        r.game.toLocaleLowerCase().includes(needle)
      }
      searchLabel="Search updates"
      searchPlaceholder="Search games and files"
      actions={actions}
      actionsClassName="w-24"
      meta={meta}
    />
  );
}
