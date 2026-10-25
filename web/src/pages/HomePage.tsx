import { useMutation } from "@tanstack/react-query";
import { Download, FileSearch, Info, RefreshCw, TriangleAlert } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { StopButton } from "@/components/apply/RunPanel";
import { PlatformIcon } from "@/components/PlatformIcon";
import { ProgressFill } from "@/components/ProgressFill";
import { type ChipTone, QuickViewBar } from "@/components/QuickViewBar";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ApiError, api } from "@/lib/api";
import { useStopConversion, waitingText } from "@/lib/conversion";
import { formatBytes, formatCount, formatFiles, formatWhen } from "@/lib/format";
import { foldersByName } from "@/lib/platforms";
import { invalidateFolder, useFolders, useMeta } from "@/lib/queries";
import { runWords, scanProgress, useStartCheck, useStartScan } from "@/lib/scan";
import {
  folderState,
  needsConversion,
  openingSection,
  renamesLeft,
  sectionPath,
  updatesLeft,
} from "@/lib/sections";
import { readJson, writeJson } from "@/lib/storage";
import type { FolderCard } from "@/lib/types";
import { cn } from "@/lib/utils";

/** One figure on a card, with the hint shown on hover. */
type Stat = { label: string; value: string; hint: string; attention?: boolean };

const DETAIL_KEY = "g1r.home.detail.v1";
const DETAILS = [
  { id: "simplified", label: "Simplified" },
  { id: "extended", label: "Extended" },
] as const;
type Detail = (typeof DETAILS)[number]["id"];

/** Nothing left to do: every file processed (a folder not scanned yet has no files) and no
 * older update to discard. */
function isCompleted(folder: FolderCard): boolean {
  return (
    folder.summary.roms > 0 &&
    folder.progress.to_process === 0 &&
    !updatesLeft(folder) &&
    !renamesLeft(folder)
  );
}

const needsMatching = (f: FolderCard) => f.progress.to_match > 0;
/** Waiting for a scan: never scanned, the last scan failed, or the DAT changed since. */
const needsScan = (f: FolderCard) => f.needs_scan;

/** The card's border: needing a scan, done, else needing conversion (it opens there), else
 * matching, else renaming. */
function cardTone(folder: FolderCard): ChipTone | null {
  if (needsScan(folder)) return "unscanned";
  if (isCompleted(folder)) return "good";
  if (needsConversion(folder)) return "convert";
  if (needsMatching(folder)) return "match";
  if (renamesLeft(folder)) return "rename";
  return null;
}
// Literal class names, so Tailwind generates them; ring-1 makes 2px without a layout shift.
const CARD_BORDERS: Record<ChipTone, string> = {
  good: "border-status-good ring-1 ring-status-good hover:border-status-good",
  convert: "border-status-convert ring-1 ring-status-convert hover:border-status-convert",
  match: "border-status-match ring-1 ring-status-match hover:border-status-match",
  unscanned: "border-status-unscanned ring-1 ring-status-unscanned hover:border-status-unscanned",
  rename: "border-status-rename ring-1 ring-status-rename hover:border-status-rename",
};

// v1 held one badge; v2 holds the list of badges chosen.
const SHOW_KEY = "g1r.home.show.v2";
/** The badges above the cards: which sets to show. Several can be on (a set shows when it is
 * in any of them); All turns the others off. */
const SHOWS = [
  { id: "all", label: "All", test: () => true },
  { id: "done", label: "Done", test: isCompleted, tone: "good" },
  { id: "conversion", label: "Needs conversion", test: needsConversion, tone: "convert" },
  { id: "matching", label: "Needs matching", test: needsMatching, tone: "match" },
  { id: "rename", label: "Needs renaming", test: renamesLeft, tone: "rename" },
  { id: "unscanned", label: "Needs scanning", test: needsScan, tone: "unscanned" },
] as const satisfies readonly {
  id: string;
  label: string;
  test: (f: FolderCard) => boolean;
  tone?: ChipTone;
}[];
type Show = (typeof SHOWS)[number]["id"];

const ALL: Show[] = ["all"];

function isShow(value: unknown): value is Show {
  return SHOWS.some((s) => s.id === value);
}

function isShows(value: unknown): value is Show[] {
  return Array.isArray(value) && value.length > 0 && value.every(isShow);
}

/** Clicking a badge: All alone, or the others toggled (none left is All again). */
function toggleShow(current: Show[], id: Show): Show[] {
  if (id === "all") return ALL;
  const others = current.filter((s) => s !== "all");
  const next = others.includes(id) ? others.filter((s) => s !== id) : [...others, id];
  return next.length > 0 ? next : ALL;
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

const PERCENT = new Intl.NumberFormat("en-US", { style: "percent" });

/** How far the folder's running conversion is, and a line saying so. Null when none runs. */
function conversionProgress(folder: FolderCard): { fraction: number; text: ReactNode } | null {
  const run = folder.converting;
  if (!run) return null;
  const fraction = run.total > 0 ? Math.min(run.done / run.total, 1) : 0;
  return {
    fraction,
    text: (
      <>
        {waitingText(run.waiting_for) ?? (
          <>
            {run.stopping ? "Stopping" : "Converting"}: {PERCENT.format(fraction)}
          </>
        )}
        {run.failed > 0 ? (
          <span className="text-status-bad"> · {formatFiles(run.failed)} failed</span>
        ) : null}
      </>
    ),
  };
}

/** Behind the card, the running scan's or conversion's progress (a folder runs one job at a
 * time). */
function CardProgress({ folder }: { folder: FolderCard }) {
  const scan = scanProgress(folder.scan);
  const converting = conversionProgress(folder);
  const progress = scan ?? converting;
  if (!progress) return null;
  return (
    <ProgressFill
      fraction={progress.fraction}
      testId={scan ? "scan-progress" : "conversion-progress"}
      className={scan ? "bg-primary/10" : "bg-status-convert/15"}
    />
  );
}

/** Scan, and before it the platform's default DAT when the set has none. */
// Most severe first.
const SEVERITY = ["bad", "warn", "info"] as const;

/** The card's warnings in a two-line slot (left out when there are none), most severe first;
 * the full text shows on hover. */
// `status` (Simplified: a running or failed scan) leads the block, so no line is kept empty for it.
function Warnings({
  folder,
  status,
  onOpen,
}: {
  folder: FolderCard;
  status?: ReactNode;
  onOpen: () => void;
}) {
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
      {status ? <span className="block truncate">{status}</span> : null}
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

/** Why a set cannot be scanned yet: it needs a DAT. */
function datGuard(folder: FolderCard): string | undefined {
  if (!folder.needs_dat) return undefined;
  return folder.dat_download
    ? "Please download the DAT first"
    : "Please upload a DAT in Settings → DATs first";
}

/** What a set without ROM files yet is waiting for: a DAT, a check or a scan. */
function emptyNote(folder: FolderCard): string {
  const guard = datGuard(folder);
  if (guard) return guard;
  if (folder.needs === "check") return "Please check files";
  if (folder.needs) return "Please scan";
  return "No ROM files found";
}

/** Stands in for the figures while a set has none: a darker box over the free space above
 * the buttons, its note centred. */
function EmptyBox({ folder, children }: { folder: FolderCard; children: ReactNode }) {
  return (
    <div
      className="mt-3 flex flex-1 items-center justify-center rounded-md bg-muted p-4 text-center text-muted-foreground text-sm dark:bg-background"
      data-testid={`empty-${folder.label}`}
    >
      {children}
    </div>
  );
}

function CardActions({ folder }: { folder: FolderCard }) {
  const scan = useStartScan(folder.label);
  const check = useStartCheck(folder.label);
  const stop = useStopConversion(folder.label);
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
  // The run that is due: Check files first (it needs no DAT), then Scan.
  const checking = folder.needs === "check";
  // A Scan waits for every file to be in the target format (converted or discarded first).
  const guard = checking
    ? undefined
    : (datGuard(folder) ??
      (folder.progress.to_convert > 0
        ? "Convert or discard first (Conversion tab): scanning waits until every file is in the target format"
        : undefined));
  return (
    <div className="relative flex flex-wrap items-center gap-2 px-4 pb-4">
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
        aria-label={`${checking ? "Check files of" : "Scan"} ${folder.label}`}
        title={
          guard ??
          (folder.converting
            ? "A conversion is running"
            : checking
              ? "List the folder and read what conversion needs; nothing is hashed"
              : "Identify the files with nothing left to convert")
        }
        disabled={
          Boolean(guard) ||
          running ||
          Boolean(folder.converting) ||
          scan.isPending ||
          check.isPending
        }
        onClick={() => (checking ? check.mutate() : scan.mutate({}))}
      >
        {checking ? (
          <FileSearch className={running ? "size-4 animate-spin" : "size-4"} aria-hidden="true" />
        ) : (
          <RefreshCw className={running ? "size-4 animate-spin" : "size-4"} aria-hidden="true" />
        )}
        {checking ? "Check files" : "Scan"}
      </Button>
      {folder.converting ? (
        <StopButton
          label={folder.label}
          stopping={folder.converting.stopping || stop.isPending}
          onStop={() => stop.mutate()}
        />
      ) : null}
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
  const [show, setShow] = useState<Show[]>(() => readJson(SHOW_KEY, ALL, isShows));
  const changeShow = (id: string) => {
    if (!isShow(id)) return;
    const next = toggleShow(show, id);
    setShow(next);
    writeJson(SHOW_KEY, next);
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
  const filters = SHOWS.filter((s) => show.includes(s.id));
  const shown = visible.filter((f) => filters.some((s) => s.test(f)));
  // The header sits in the card grid, so it spans exactly the centred columns.
  return (
    // Every card row is as tall as the tallest card (auto-rows-fr), so all cards of a view
    // have one size; the header keeps its own height.
    <div className="grid auto-rows-fr grid-cols-[repeat(auto-fill,18rem)] grid-rows-[auto] justify-center gap-4">
      <header className="col-span-full mb-2 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-64 flex-1">
          <h1 className="font-semibold text-2xl tracking-tight">Home</h1>
          {hidden > 0 ? (
            <p className="text-muted-foreground text-sm">
              {formatCount(hidden)} hidden {hidden === 1 ? "set is" : "sets are"} left out (
              <Link to="/settings/romsets" className="underline underline-offset-2">
                Settings → Romset management
              </Link>
              ).
            </p>
          ) : null}
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
            No set is {filters.map((s) => s.label.toLowerCase()).join(" or ")} right now.{" "}
            <strong>All</strong> shows every set.
          </p>
        </div>
      ) : shown.length === 0 ? (
        <div className="col-span-full max-w-xl rounded-lg border border-border bg-card p-6">
          <h2 className="font-medium">No sets yet</h2>
          <p className="mt-1 text-muted-foreground text-sm">
            Add them with <strong>Add romsets</strong> at the bottom of the sidebar: one platform
            folder, or a folder holding one folder per platform, matched by name. Each set holds
            exactly one platform.
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
          const converting = conversionProgress(folder);
          // Simplified leaves out the last scan's date; a running conversion, or a running or
          // failed scan, still shows.
          const empty = folder.summary.roms === 0;
          // A running conversion or scan; on a set without figures it shows in the empty box.
          const activity = converting ? (
            <span data-testid={`conversion-status-${folder.label}`}>{converting.text}</span>
          ) : folder.scan?.status !== "done" && progress ? (
            <span data-testid={`scan-status-${folder.label}`}>{progress.text}</span>
          ) : null;
          const scanLine =
            activity && !empty ? (
              activity
            ) : folder.scan ? (
              folder.scan.status === "done" ? (
                extended ? (
                  `${runWords(folder.scan).past} ${formatWhen(folder.scan.finished_at)}`
                ) : null
              ) : progress || empty ? null : (
                <span className="text-status-bad">Last {runWords(folder.scan).noun} failed</span>
              )
            ) : extended && !empty ? (
              <span className="text-muted-foreground">Not scanned yet</span>
            ) : null;
          // Simplified's running or failed scan leads the warnings block, so it counts too.
          const message = folder.warnings.length > 0 || (!extended && Boolean(scanLine));
          const done = isCompleted(folder);
          const tone = cardTone(folder);
          const target = sectionPath(folder.label, openingSection(folder));
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
              <CardProgress folder={folder} />
              {/* The title's link covers the card (::after); links inside sit above it. */}
              <div className="relative flex flex-1 flex-col p-4">
                <div className="flex min-w-0 items-center gap-2">
                  <PlatformIcon platform={platform} state={folderState(folder)} />
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
                {/* Fixed slots, so the figures sit at the same height on every card. Simplified
                    has no scan line: its running or failed scan leads the warnings block. */}
                {extended ? (
                  <p className="mt-2 text-xs leading-4">
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
                    {empty && !scanLine ? null : (
                      <span className="block min-h-4 truncate">{scanLine}</span>
                    )}
                  </p>
                ) : null}
                {/* No empty slot: without a message, the figures (or the empty box) take the
                    space down to the buttons, centred. */}
                {message ? (
                  <Warnings
                    folder={folder}
                    status={extended ? null : scanLine}
                    onOpen={() => navigate(target)}
                  />
                ) : null}
                {!empty ? (
                  <dl
                    className={cn(
                      "grid grid-cols-2 gap-x-4 gap-y-2",
                      message ? "mt-3" : "mt-3 flex-1 content-center",
                    )}
                    data-testid={`figures-${folder.label}`}
                  >
                    {stats.map((s) => (
                      <Tooltip key={s.label}>
                        {/* Above the card's link so the hint shows; a click still opens the set. */}
                        <TooltipTrigger asChild>
                          {/* biome-ignore lint/a11y/noStaticElementInteractions lint/a11y/useKeyWithClickEvents: the card's title link is the keyboard path; this keeps a click on a figure opening the set. */}
                          <div
                            className="relative z-10 cursor-pointer even:text-right"
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
                ) : (
                  <EmptyBox folder={folder}>{activity ?? emptyNote(folder)}</EmptyBox>
                )}
              </div>
              <CardActions folder={folder} />
            </div>
          );
        })
      )}
    </div>
  );
}
