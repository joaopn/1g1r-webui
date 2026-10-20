import { useMutation } from "@tanstack/react-query";
import { Download, Info, RefreshCw, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { PlatformIcon } from "@/components/PlatformIcon";
import { type ChipTone, QuickViewBar } from "@/components/QuickViewBar";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError, api } from "@/lib/api";
import { formatBytes, formatCount, formatFiles, formatWhen } from "@/lib/format";
import { foldersByName } from "@/lib/platforms";
import { invalidateFolder, useFolders, useMeta } from "@/lib/queries";
import { scanProgress, useStartScan } from "@/lib/scan";
import { readJson, writeJson } from "@/lib/storage";
import type { FolderCard, Scan } from "@/lib/types";
import { cn } from "@/lib/utils";

/** One figure on a card, with the hint shown on hover. */
type Stat = { label: string; value: string; hint: string; attention?: boolean };

const DETAIL_KEY = "g1r.home.detail.v1";
const DETAILS = [
  { id: "simplified", label: "Simplified" },
  { id: "extended", label: "Extended" },
] as const;
type Detail = (typeof DETAILS)[number]["id"];

/** Nothing left to do: every file processed (a folder not scanned yet has no files). */
function isCompleted(folder: FolderCard): boolean {
  return folder.summary.roms > 0 && folder.progress.to_process === 0;
}

const needsConversion = (f: FolderCard) => f.progress.to_convert > 0;
const needsMatching = (f: FolderCard) => f.progress.to_match > 0;
/** No scan started yet (a running or failed first scan has left this state). */
const neverScanned = (f: FolderCard) => f.scan === null;

/** The card's border: never scanned, done, else needing conversion (it opens there), else
 * matching. */
function cardTone(folder: FolderCard): ChipTone | null {
  if (neverScanned(folder)) return "unscanned";
  if (isCompleted(folder)) return "good";
  if (needsConversion(folder)) return "convert";
  if (needsMatching(folder)) return "match";
  return null;
}
// Literal class names, so Tailwind generates them; ring-1 makes 2px without a layout shift.
const CARD_BORDERS: Record<ChipTone, string> = {
  good: "border-status-good ring-1 ring-status-good hover:border-status-good",
  convert: "border-status-convert ring-1 ring-status-convert hover:border-status-convert",
  match: "border-status-match ring-1 ring-status-match hover:border-status-match",
  unscanned: "border-status-unscanned ring-1 ring-status-unscanned hover:border-status-unscanned",
};

const SHOW_KEY = "g1r.home.show.v1";
/** The badges above the cards: which sets to show, one at a time. */
const SHOWS = [
  { id: "all", label: "All", test: () => true },
  { id: "done", label: "Done", test: isCompleted, tone: "good" },
  { id: "conversion", label: "Needing conversion", test: needsConversion, tone: "convert" },
  { id: "matching", label: "Needing matching", test: needsMatching, tone: "match" },
  { id: "unscanned", label: "Never scanned", test: neverScanned, tone: "unscanned" },
] as const satisfies readonly {
  id: string;
  label: string;
  test: (f: FolderCard) => boolean;
  tone?: ChipTone;
}[];
type Show = (typeof SHOWS)[number]["id"];

function isShow(value: unknown): value is Show {
  return SHOWS.some((s) => s.id === value);
}

function isDetail(value: unknown): value is Detail {
  return DETAILS.some((d) => d.id === value);
}

/** Simplified | Extended: how much each card shows, remembered per browser. */
function DetailSwitch({ value, onChange }: { value: Detail; onChange: (d: Detail) => void }) {
  return (
    <fieldset className="flex shrink-0 overflow-hidden rounded-full border border-border text-sm">
      <legend className="sr-only">Card detail</legend>
      {DETAILS.map((d) => {
        const active = d.id === value;
        return (
          <label
            key={d.id}
            className={cn(
              "cursor-pointer px-3 py-1 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
              active
                ? "bg-primary text-primary-foreground"
                : "bg-card hover:bg-accent hover:text-accent-foreground",
            )}
          >
            <input
              type="radio"
              name="home-detail"
              className="sr-only"
              value={d.id}
              checked={active}
              onChange={() => onChange(d.id)}
            />
            {d.label}
          </label>
        );
      })}
    </fieldset>
  );
}

/** The card's scan button and, behind the card, the running scan's progress. */
function ScanBackground({ scan }: { scan: Scan | null }) {
  const progress = scanProgress(scan);
  if (!progress) return null;
  return (
    <div
      aria-hidden="true"
      data-testid="scan-progress"
      className={cn(
        "pointer-events-none absolute inset-0 origin-left bg-primary/10 transition-transform duration-500",
        progress.fraction === null && "animate-pulse",
      )}
      style={progress.fraction === null ? undefined : { transform: `scaleX(${progress.fraction})` }}
    />
  );
}

/** Scan, and before it the platform's default DAT when the set has none. */
// Most severe first.
const SEVERITY = ["bad", "warn", "info"] as const;

/** The card's warnings in a two-line slot (empty when there are none), most severe first;
 * the full text shows on hover. */
function Warnings({ folder, onOpen }: { folder: FolderCard; onOpen: () => void }) {
  const warnings = [...folder.warnings].sort(
    (a, b) => SEVERITY.indexOf(a.level) - SEVERITY.indexOf(b.level),
  );
  const text = (
    // biome-ignore lint/a11y/noStaticElementInteractions lint/a11y/useKeyWithClickEvents: the card's title link is the keyboard path; this keeps a click on the warnings opening the set.
    <p
      className="relative z-10 mt-3 line-clamp-2 h-8 cursor-pointer text-xs leading-4"
      data-testid={`warnings-${folder.label}`}
      onClick={onOpen}
    >
      {warnings.map((w) => {
        const Icon = w.level === "info" ? Info : TriangleAlert;
        return (
          <span
            key={w.text}
            className={cn(
              w.level === "bad"
                ? "text-status-bad"
                : w.level === "warn"
                  ? "text-status-warn"
                  : "text-muted-foreground",
            )}
          >
            <Icon className="-mt-0.5 mr-1 inline size-3.5" aria-hidden="true" />
            {w.text}
            {w.link ? (
              <>
                {" "}
                <Link
                  to={w.link.to}
                  className="text-primary underline underline-offset-2"
                  onClick={(e) => e.stopPropagation()}
                >
                  {w.link.text}
                </Link>
              </>
            ) : null}{" "}
          </span>
        );
      })}
    </p>
  );
  if (warnings.length === 0) return text;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{text}</TooltipTrigger>
      <TooltipContent className="max-w-72" data-testid={`warnings-full-${folder.label}`}>
        <ul className="space-y-1">
          {warnings.map((w) => (
            <li key={w.text}>{w.text}</li>
          ))}
        </ul>
      </TooltipContent>
    </Tooltip>
  );
}

function CardActions({ folder }: { folder: FolderCard }) {
  const scan = useStartScan(folder.label);
  const download = useMutation({
    mutationFn: (source: string) =>
      api(`/dats/${folder.platform}/download?source=${encodeURIComponent(source)}`, {
        method: "POST",
      }),
    onSuccess: () => {
      toast.success(`${folder.label}: DAT downloaded from ${folder.dat_download?.label}`);
      invalidateFolder(folder.label);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  const running = folder.scan?.status === "running";
  const guard = folder.needs_dat
    ? folder.dat_download
      ? "Download the DAT first"
      : "Upload a DAT in Settings → DATs first"
    : undefined;
  return (
    <div className="relative mt-auto flex flex-wrap items-center gap-2 px-4 pb-4">
      {folder.dat_download ? (
        <Button
          size="sm"
          disabled={download.isPending}
          title={`From ${folder.dat_download.label}`}
          onClick={() => folder.dat_download && download.mutate(folder.dat_download.source)}
        >
          <Download className="size-4" aria-hidden="true" />
          {download.isPending ? "Downloading DAT…" : "Download DAT"}
        </Button>
      ) : null}
      <Button
        size="sm"
        variant="outline"
        aria-label={`Scan ${folder.label}`}
        title={guard ?? "Scan for conversion and matching"}
        disabled={Boolean(guard) || running || scan.isPending}
        onClick={() => scan.mutate({})}
      >
        <RefreshCw className={running ? "size-4 animate-spin" : "size-4"} aria-hidden="true" />
        Scan
      </Button>
      {guard ? <span className="text-muted-foreground text-xs">{guard}</span> : null}
    </div>
  );
}

export function HomePage() {
  const meta = useMeta();
  const folders = useFolders();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<Detail>(() => readJson(DETAIL_KEY, "extended", isDetail));
  const changeDetail = (d: Detail) => {
    setDetail(d);
    writeJson(DETAIL_KEY, d);
  };
  const extended = detail === "extended";
  const [show, setShow] = useState<Show>(() => readJson(SHOW_KEY, "all", isShow));
  const changeShow = (id: string) => {
    if (!isShow(id)) return;
    setShow(id);
    writeJson(SHOW_KEY, id);
  };
  if (!meta.data || !folders.data) return <p className="text-muted-foreground">Loading…</p>;
  const ui = meta.data.ui;
  const visible = folders.data.filter((f) => !f.hidden);
  const hidden = folders.data.length - visible.length;
  const views = SHOWS.map((s) => ({
    id: s.id,
    label: s.label,
    count: visible.filter(s.test).length,
    tone: "tone" in s ? s.tone : undefined,
  }));
  const filter = SHOWS.find((s) => s.id === show) ?? SHOWS[0];
  const shown = visible.filter(filter.test);
  // The header sits in the card grid, so it spans exactly the centred columns.
  return (
    // Every card row is as tall as the tallest card (auto-rows-fr), so all cards of a view
    // have one size; the header keeps its own height.
    <div className="grid auto-rows-fr grid-cols-[repeat(auto-fill,18rem)] grid-rows-[auto] justify-center gap-4">
      <header className="col-span-full mb-2 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-64 flex-1">
          <h1 className="font-semibold text-2xl tracking-tight">Home</h1>
          <p className="text-muted-foreground text-sm">
            Everything here is a proposal until you apply it, and what is applied can be undone.
            {hidden > 0 ? (
              <>
                {" "}
                {formatCount(hidden)} hidden {hidden === 1 ? "set is" : "sets are"} left out (
                <Link to="/settings/folders" className="underline underline-offset-2">
                  Settings → Folders
                </Link>
                ).
              </>
            ) : null}
          </p>
        </div>
        <DetailSwitch value={detail} onChange={changeDetail} />
        {visible.length > 0 ? (
          <div className="basis-full">
            <QuickViewBar name="home-show" views={views} value={show} onChange={changeShow} />
          </div>
        ) : null}
      </header>
      {shown.length === 0 && visible.length > 0 ? (
        <div className="col-span-full max-w-xl rounded-lg border border-border bg-card p-6">
          <h2 className="font-medium">No set here</h2>
          <p className="mt-1 text-muted-foreground text-sm">
            No set is {filter.label.toLowerCase()} right now. <strong>All</strong> shows every set.
          </p>
        </div>
      ) : shown.length === 0 ? (
        <div className="col-span-full max-w-xl rounded-lg border border-border bg-card p-6">
          <h2 className="font-medium">No sets yet</h2>
          <p className="mt-1 text-muted-foreground text-sm">
            Add a platform folder with <strong>Add set</strong> at the bottom of the sidebar, or a
            folder holding one folder per platform with <strong>Add sets from a folder</strong>.
            Each set holds exactly one platform.
          </p>
        </div>
      ) : (
        foldersByName(shown, meta.data.platforms).map((folder) => {
          const platform = meta.data.platforms[folder.platform];
          const size: Stat = {
            label: "folder size",
            value: formatBytes(folder.summary.bytes, ui.byte_unit_base, ui.byte_units),
            hint: "Size of the ROM files in the folder",
          };
          const stats: Stat[] = extended
            ? [
                {
                  label: "identified",
                  value: `${formatCount(folder.summary.identified)} / ${formatCount(folder.summary.roms)}`,
                  hint: "ROM files identified by a DAT, Hasheous or by hand, out of all ROM files",
                },
                {
                  label: "unmatched",
                  value: formatCount(folder.summary.unmatched),
                  attention: folder.summary.unmatched > 0,
                  hint: "ROM files nothing identified yet",
                },
                {
                  label: "games with several versions",
                  value: formatCount(folder.counts.several ?? 0),
                  hint: "Games with more than one version in the folder",
                },
                {
                  label: "undecided",
                  value: formatCount(folder.counts.undecided ?? 0),
                  attention: (folder.counts.undecided ?? 0) > 0,
                  hint: "Games where the ranking cannot pick the version to keep: choose one on the Matching page",
                },
                {
                  label: "proposed moves",
                  value: formatCount(folder.counts.proposals ?? 0),
                  hint: "Games with versions proposed to move to discarded/ by Apply 1G1R",
                },
                {
                  label: "to convert",
                  value: formatCount(folder.conversion.to_convert),
                  attention: folder.conversion.to_convert > 0,
                  hint: "Conversions waiting to be applied on the Conversion page (a multi-file disc counts once)",
                },
                {
                  label: "conversions flagged",
                  value: formatCount(folder.conversion.flagged),
                  attention: folder.conversion.flagged > 0,
                  hint: "Conversions that need a look on the Conversion page before they can run",
                },
                size,
                {
                  label: "would free",
                  value: formatBytes(folder.reclaim_bytes, ui.byte_unit_base, ui.byte_units),
                  hint: "Space the proposed moves would free in the folder",
                },
                {
                  label:
                    folder.discarded.files > 0
                      ? `already discarded · ${formatFiles(folder.discarded.files)}`
                      : "already discarded",
                  value:
                    folder.discarded.files > 0
                      ? formatBytes(folder.discarded.bytes, ui.byte_unit_base, ui.byte_units)
                      : "nothing",
                  hint: "Files already moved to discarded/, and their size",
                },
              ]
            : [
                {
                  label: "processed",
                  value: `${formatCount(folder.progress.processed)} / ${formatCount(folder.summary.roms)}`,
                  hint: "ROM files with nothing left to do, out of all ROM files",
                },
                size,
                {
                  label: "to convert",
                  value: formatCount(folder.progress.to_convert),
                  attention: folder.progress.to_convert > 0,
                  hint: "ROM files waiting for a conversion, or flagged for a look, on the Conversion page",
                },
                {
                  label: "to match",
                  value: formatCount(folder.progress.to_match),
                  attention: folder.progress.to_match > 0,
                  hint: "ROM files unmatched, or in a game undecided or with a move proposed, on the Matching page. A file can be both to match and to convert",
                },
              ];
          const progress = scanProgress(folder.scan);
          // Simplified leaves out the last scan's date; a running or failed scan still shows.
          const scanLine = folder.scan ? (
            folder.scan.status === "done" ? (
              extended ? (
                `Scanned ${formatWhen(folder.scan.finished_at)}`
              ) : null
            ) : progress ? (
              <span data-testid={`scan-status-${folder.label}`}>{progress.text}</span>
            ) : (
              <span className="text-status-bad">Last scan failed</span>
            )
          ) : extended ? (
            <span className="text-muted-foreground">Not scanned yet</span>
          ) : null;
          const done = isCompleted(folder);
          const tone = cardTone(folder);
          // Pending conversions come first: the card opens where there is work to apply.
          const page = folder.conversion.to_convert > 0 ? "conversion" : "matching";
          const target = `/folders/${folder.label}/${page}`;
          return (
            <div
              key={folder.label}
              data-testid={`folder-card-${folder.label}`}
              data-done={done || undefined}
              data-tone={tone ?? undefined}
              className={cn(
                "group relative flex flex-col overflow-hidden rounded-lg border bg-card transition-colors hover:bg-accent/30",
                tone ? CARD_BORDERS[tone] : "border-border hover:border-primary/50",
              )}
            >
              <ScanBackground scan={folder.scan} />
              {/* The title's link covers the card (::after); links inside sit above it. */}
              <div className="relative p-4">
                <div className="flex min-w-0 items-center gap-2">
                  <PlatformIcon platform={platform} />
                  <h2
                    className="min-w-0 truncate font-medium group-hover:text-primary"
                    title={platform?.name ?? folder.platform}
                  >
                    <Link to={target} className="after:absolute after:inset-0 after:content-['']">
                      {platform?.name ?? folder.platform}
                    </Link>
                  </h2>
                  <span className="shrink-0 text-muted-foreground text-sm">{folder.label}</span>
                </div>
                <p className="mt-1 truncate text-muted-foreground text-xs">
                  {folder.location ?? `mount ${folder.mount} unavailable`}
                </p>
                {/* Fixed slots, so the figures sit at the same height on every card. */}
                <p className="mt-2 text-xs leading-4">
                  {extended ? (
                    <span
                      className="block truncate"
                      title={
                        folder.dat
                          ? `${folder.dat.header_name} · ${folder.dat.version ?? "?"}`
                          : undefined
                      }
                    >
                      {folder.dat ? (
                        `DAT ${folder.dat.header_name} · ${folder.dat.version ?? "?"}`
                      ) : (
                        <span className="text-status-warn">No DAT yet</span>
                      )}
                    </span>
                  ) : null}
                  <span className="block min-h-4 truncate">{scanLine}</span>
                </p>
                <Warnings folder={folder} onOpen={() => navigate(target)} />
                {folder.summary.roms > 0 ? (
                  <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
                    {stats.map((s) => (
                      <Tooltip key={s.label}>
                        {/* Above the card's link so the hint shows; a click still opens the set. */}
                        <TooltipTrigger asChild>
                          {/* biome-ignore lint/a11y/noStaticElementInteractions lint/a11y/useKeyWithClickEvents: the card's title link is the keyboard path; this keeps a click on a figure opening the set. */}
                          <div
                            className="relative z-10 cursor-pointer"
                            onClick={() => navigate(target)}
                          >
                            <dt className="text-muted-foreground text-xs">{s.label}</dt>
                            <dd
                              className={cn(
                                "font-semibold tabular-nums",
                                s.attention && "text-status-warn",
                              )}
                            >
                              {s.value}
                            </dd>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-64">{s.hint}</TooltipContent>
                      </Tooltip>
                    ))}
                  </dl>
                ) : null}
              </div>
              <CardActions folder={folder} />
            </div>
          );
        })
      )}
    </div>
  );
}
