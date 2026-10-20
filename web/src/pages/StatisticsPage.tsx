import { ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { PlatformIcon } from "@/components/PlatformIcon";
import { type DataColumn, DataTable, type RowView } from "@/components/table/DataTable";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatCount } from "@/lib/format";
import { useMeta, useMissing, useStatistics } from "@/lib/queries";
import type { DatInfo, Meta, MissingGame, Statistics, StatisticsFolder } from "@/lib/types";

const ALL: RowView<StatisticsFolder>[] = [{ id: "all", label: "All", test: () => true }];
const ALL_MISSING: RowView<MissingGame>[] = [{ id: "all", label: "All", test: () => true }];
// The missing-games table's URL parameters, apart from the page table's.
const MISSING_PREFIX = "m.";

const share = (covered: number, total: number) => (total ? covered / total : 0);
const percent = (value: number, digits: number) =>
  value.toLocaleString("en-US", {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

/** Statistics: per folder, the identified files and how much of each local DAT it covers. */
export function StatisticsPage() {
  const meta = useMeta();
  const stats = useStatistics();
  const [open, setOpen] = useState<{ label: string; source: string } | null>(null);
  const [params, setParams] = useSearchParams();

  const close = () => {
    setOpen(null);
    const next = new URLSearchParams(params);
    for (const key of [...next.keys()]) if (key.startsWith(MISSING_PREFIX)) next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-semibold text-2xl tracking-tight">Statistics</h1>
        <p className="text-muted-foreground text-sm">
          Games of each local DAT found in the set. Click a percentage for the missing games.
        </p>
      </div>
      {stats.isError ? <p className="text-destructive text-sm">{String(stats.error)}</p> : null}
      {meta.data && stats.data ? (
        <>
          <CoverageTable meta={meta.data} stats={stats.data} onOpen={setOpen} />
          <DatInfoSection stats={stats.data} />
          <Dialog open={open !== null} onOpenChange={(o) => (o ? null : close())}>
            {open ? (
              <MissingDialog
                meta={meta.data}
                label={open.label}
                source={stats.data.sources.find((s) => s.id === open.source)?.label ?? open.source}
                sourceId={open.source}
              />
            ) : null}
          </Dialog>
        </>
      ) : (
        <p className="text-muted-foreground text-sm">Loading…</p>
      )}
    </div>
  );
}

function CoverageTable({
  meta,
  stats,
  onOpen,
}: {
  meta: Meta;
  stats: Statistics;
  onOpen: (target: { label: string; source: string }) => void;
}) {
  const digits = meta.ui.percent_digits;
  // Only sources some folder has a DAT of get a column.
  const sources = stats.sources.filter((s) => stats.folders.some((f) => s.id in f.coverage));
  const columns = useMemo<DataColumn<StatisticsFolder>[]>(
    () => [
      {
        id: "folder",
        label: "Set",
        render: (f) => <span className="font-medium">{f.label}</span>,
        sortValue: (f) => f.label,
      },
      {
        id: "platform",
        label: "Platform",
        render: (f) => <PlatformIcon platform={meta.platforms[f.platform]} />,
        sortValue: (f) => f.platform_short,
        title: (f) => meta.platforms[f.platform]?.name,
      },
      {
        id: "identified",
        label: "Identified",
        render: (f) => (
          <span className="tabular-nums">
            {formatCount(f.identified)} / {formatCount(f.roms)}
          </span>
        ),
        sortValue: (f) => share(f.identified, f.roms),
        title: (f) => `${formatCount(f.identified)} of ${formatCount(f.roms)} ROM files identified`,
      },
      ...sources.map(
        (s): DataColumn<StatisticsFolder> => ({
          id: s.id,
          label: s.short_label,
          className: "text-right",
          render: (f) => {
            const cell = f.coverage[s.id];
            if (!cell) return null;
            return (
              <button
                type="button"
                className="rounded px-1 tabular-nums underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
                onClick={() => onOpen({ label: f.label, source: s.id })}
                data-testid={`coverage-${f.label}-${s.id}`}
              >
                {percent(share(cell.covered, cell.total), digits)}
              </button>
            );
          },
          sortValue: (f) => {
            const cell = f.coverage[s.id];
            return cell ? share(cell.covered, cell.total) : Number.NEGATIVE_INFINITY;
          },
          title: (f) => {
            const cell = f.coverage[s.id];
            return cell
              ? `${formatCount(cell.covered)} of ${formatCount(cell.total)} games · ${cell.dat.header_name}${cell.dat.version ? ` ${cell.dat.version}` : ""}`
              : `No ${s.label} DAT for this platform`;
          },
        }),
      ),
    ],
    [meta, sources, digits, onOpen],
  );
  const sizes = {
    ...meta.ui.statistics_columns,
    ...Object.fromEntries(sources.map((s) => [s.id, meta.ui.statistics_columns.source])),
  };
  return (
    <DataTable
      name="statistics"
      label="DAT coverage"
      noun="sets"
      rows={stats.folders}
      rowKey={(f) => f.label}
      rowTestId={(f) => `statistics-${f.label}`}
      columns={columns}
      sizes={sizes}
      defaultColumns={[...meta.ui.statistics_columns_default, ...sources.map((s) => s.id)]}
      defaultSort={{ id: "folder", order: "asc" }}
      views={ALL}
      search={(f, needle) =>
        f.label.toLocaleLowerCase().includes(needle) ||
        f.platform_short.toLocaleLowerCase().includes(needle)
      }
      searchLabel="Search sets"
      searchPlaceholder="Search sets or platforms"
      filters={[
        {
          id: "platform",
          label: "Platform",
          options: [...new Set(stats.folders.map((f) => f.platform))].sort().map((p) => ({
            value: p,
            label: meta.platforms[p]?.name ?? p,
          })),
          valueOf: (f) => f.platform,
        },
      ]}
      meta={meta}
    />
  );
}

function MissingDialog({
  meta,
  label,
  source,
  sourceId,
}: {
  meta: Meta;
  label: string;
  source: string;
  sourceId: string;
}) {
  const missing = useMissing(label, sourceId);
  const text = (value: string | null) => value ?? "";
  const columns: DataColumn<MissingGame>[] = [
    {
      id: "name",
      label: "Game",
      render: (g) => g.name,
      sortValue: (g) => g.name.toLocaleLowerCase(),
      title: (g) => g.entries.join("\n"),
    },
    { id: "years", label: "Year", render: (g) => text(g.years), sortValue: (g) => text(g.years) },
    {
      id: "publishers",
      label: "Publisher",
      render: (g) => text(g.publishers),
      sortValue: (g) => text(g.publishers),
      title: (g) => g.publishers ?? undefined,
    },
    {
      id: "regions",
      label: "Regions",
      render: (g) => text(g.regions),
      sortValue: (g) => text(g.regions),
      title: (g) => g.regions ?? undefined,
    },
    {
      id: "languages",
      label: "Languages",
      render: (g) => text(g.languages),
      sortValue: (g) => text(g.languages),
      title: (g) => g.languages ?? undefined,
    },
    {
      id: "serials",
      label: "Serial",
      render: (g) => text(g.serials),
      sortValue: (g) => text(g.serials),
      title: (g) => g.serials ?? undefined,
    },
    {
      id: "versions",
      label: "Versions",
      className: "text-right tabular-nums",
      render: (g) => formatCount(g.versions),
      sortValue: (g) => g.versions,
      title: (g) => g.entries.join("\n"),
    },
  ];
  // A column no missing game has a value for starts hidden.
  const hasData = (id: string) => !isOptional(id) || (missing.data?.rows ?? []).some((g) => g[id]);
  return (
    <DialogContent
      className="max-h-[90vh] overflow-y-auto sm:max-w-5xl"
      data-testid="missing-dialog"
    >
      <DialogHeader>
        <DialogTitle>
          {label} · missing from {source}
        </DialogTitle>
        <DialogDescription>
          {missing.data
            ? `${formatCount(missing.data.total - missing.data.covered)} of ${formatCount(missing.data.total)} games not in the set · ${missing.data.dat.header_name}${missing.data.dat.version ? ` ${missing.data.dat.version}` : ""}`
            : "Loading…"}
        </DialogDescription>
      </DialogHeader>
      {missing.isError ? <p className="text-destructive text-sm">{String(missing.error)}</p> : null}
      {missing.data ? (
        <DataTable
          name="missing"
          label="Missing games"
          noun="games"
          rows={missing.data.rows}
          rowKey={(g) => g.key}
          rowTestId={(g) => `missing-${g.key}`}
          columns={columns}
          sizes={meta.ui.missing_columns}
          defaultColumns={meta.ui.missing_columns_default.filter((id) => hasData(id))}
          defaultSort={{ id: "name", order: "asc" }}
          views={ALL_MISSING}
          search={(g, needle) =>
            g.name.toLocaleLowerCase().includes(needle) ||
            g.entries.some((e) => e.toLocaleLowerCase().includes(needle))
          }
          searchLabel="Search missing games"
          searchPlaceholder="Search games"
          meta={meta}
          paramPrefix={MISSING_PREFIX}
          note="values of different versions are joined with commas"
        />
      ) : null}
    </DialogContent>
  );
}

// The missing games' columns a DAT may have no data for (No-Intro and Redump give no years).
const OPTIONAL = ["years", "publishers", "regions", "languages", "serials"] as const;
type Optional = (typeof OPTIONAL)[number];
const isOptional = (id: string): id is Optional => (OPTIONAL as readonly string[]).includes(id);

const yesNo = (value: boolean) => (value ? "yes" : "no");

function DatInfoSection({ stats }: { stats: Statistics }) {
  const rows = stats.dat_info.filter((d) => d.dats > 0);
  const { rules } = stats;
  return (
    <details className="group rounded-lg border border-border bg-card" data-testid="dat-info">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="size-4 text-muted-foreground transition-transform group-open:rotate-90 motion-reduce:transition-none"
          aria-hidden="true"
        />
        DAT info
      </summary>
      <div className="space-y-3 border-border border-t px-4 py-3 text-sm">
        <div className="space-y-2 text-muted-foreground">
          <p>
            Only games count. A DAT entry is left out when its DAT category is not{" "}
            {rules.categories.join(", ")}; when a tag of its name or ROM names starts with{" "}
            {rules.excluded_tags.join(", ")}; when it is a BIOS; and for TOSEC, when it is a
            pre-release or has a dump flag{" "}
            {rules.tosec_excluded_flags.map((f) => `[${f}]`).join(" ")}. Unlicensed (Unl) releases
            count.
          </p>
          <p>
            A game is the group of its versions, formed as on the Matching page (DAT parent/clone
            data, Retool clone lists, names). It is found when one of its counted versions is in the
            set; left-out versions do not count (only a prototype in the set leaves the game
            missing), and a game with only left-out versions is not counted at all. Each disc of a
            multi-disc game is a game of its own.
          </p>
          <p>
            A file identified by another DAT counts when its ROM checksums cover every ROM of the
            game, or when the DAT lists the same name. An empty cell: the platform has no DAT from
            that source.
          </p>
        </div>
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left text-sm" aria-label="DAT sources">
            <thead className="text-muted-foreground text-xs uppercase tracking-wide">
              <tr className="border-border border-b">
                <th className="px-3 py-1.5 font-normal">Source</th>
                <th className="px-3 py-1.5 font-normal">Local DATs</th>
                <th className="px-3 py-1.5 font-normal">Checksums</th>
                <th className="px-3 py-1.5 font-normal">Categories</th>
                <th className="px-3 py-1.5 font-normal">Parent/clone</th>
                <th className="px-3 py-1.5 font-normal">BIOS flags</th>
                <th className="px-3 py-1.5 font-normal">Serials</th>
                <th className="px-3 py-1.5 font-normal">Years</th>
                <th className="px-3 py-1.5 font-normal">Publishers</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d: DatInfo) => (
                <tr
                  key={d.id}
                  className="border-border border-b last:border-b-0"
                  data-testid={`dat-info-${d.id}`}
                >
                  <td className="px-3 py-1.5 font-medium">{d.label}</td>
                  <td className="px-3 py-1.5 tabular-nums">{formatCount(d.dats)}</td>
                  <td className="px-3 py-1.5">{d.checksums.join(", ")}</td>
                  <td className="px-3 py-1.5">{d.categories.join(", ") || "none"}</td>
                  <td className="px-3 py-1.5">{yesNo(d.parent_clone)}</td>
                  <td className="px-3 py-1.5">{yesNo(d.bios)}</td>
                  <td className="px-3 py-1.5">{yesNo(d.serials)}</td>
                  <td className="px-3 py-1.5">{yesNo(d.years)}</td>
                  <td className="px-3 py-1.5">{yesNo(d.publishers)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </details>
  );
}
