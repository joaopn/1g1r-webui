import { useMutation } from "@tanstack/react-query";
import { Download, Info, RefreshCw, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { PlatformIcon } from "@/components/PlatformIcon";
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

const HIDE_COMPLETED_KEY = "g1r.home.hide-completed.v1";

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

/** Nothing left to do: every file processed (a folder not scanned yet has no files). */
function isCompleted(folder: FolderCard): boolean {
  return folder.summary.roms > 0 && folder.progress.to_process === 0;
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
  const [hideCompleted, setHideCompleted] = useState(() =>
    readJson(HIDE_COMPLETED_KEY, false, isBoolean),
  );
  const changeHideCompleted = (hide: boolean) => {
    setHideCompleted(hide);
    writeJson(HIDE_COMPLETED_KEY, hide);
  };
  if (!meta.data || !folders.data) return <p className="text-muted-foreground">Loading…</p>;
  const ui = meta.data.ui;
  const visible = folders.data.filter((f) => !f.hidden);
  const hidden = folders.data.length - visible.length;
  const shown = hideCompleted ? visible.filter((f) => !isCompleted(f)) : visible;
  const completedOut = visible.length - shown.length;
  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
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
            {completedOut > 0
              ? ` ${formatCount(completedOut)} completed ${completedOut === 1 ? "set is" : "sets are"} hidden.`
              : null}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-4">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4 accent-primary"
              checked={hideCompleted}
              onChange={(e) => changeHideCompleted(e.target.checked)}
            />
            Hide completed
          </label>
          <DetailSwitch value={detail} onChange={changeDetail} />
        </div>
      </header>
      {shown.length === 0 && completedOut > 0 ? (
        <div className="max-w-xl rounded-lg border border-border bg-card p-6">
          <h2 className="font-medium">Every set is completed</h2>
          <p className="mt-1 text-muted-foreground text-sm">
            Untick <strong>Hide completed</strong> to see them.
          </p>
        </div>
      ) : shown.length === 0 ? (
        <div className="max-w-xl rounded-lg border border-border bg-card p-6">
          <h2 className="font-medium">No sets yet</h2>
          <p className="mt-1 text-muted-foreground text-sm">
            Add a platform folder with <strong>Add set</strong> at the bottom of the sidebar, or a
            folder holding one folder per platform with <strong>Add sets from a folder</strong>.
            Each set holds exactly one platform.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,18rem)] items-start gap-4">
          {foldersByName(shown, meta.data.platforms).map((folder) => {
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
            // Pending conversions come first: the card opens where there is work to apply.
            const page = folder.conversion.to_convert > 0 ? "conversion" : "matching";
            const target = `/folders/${folder.label}/${page}`;
            return (
              <div
                key={folder.label}
                data-testid={`folder-card-${folder.label}`}
                data-done={done || undefined}
                className={cn(
                  "group relative overflow-hidden rounded-lg border bg-card transition-colors hover:bg-accent/30",
                  done
                    ? "border-status-good ring-1 ring-status-good hover:border-status-good"
                    : "border-border hover:border-primary/50",
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
                  {extended || scanLine ? (
                    <p className="mt-2 text-xs">
                      {extended ? (
                        <>
                          {folder.dat ? (
                            `DAT ${folder.dat.header_name} · ${folder.dat.version ?? "?"}`
                          ) : (
                            <span className="text-status-warn">No DAT yet</span>
                          )}
                          <br />
                        </>
                      ) : null}
                      {scanLine}
                    </p>
                  ) : null}
                  {folder.warnings.length > 0 ? (
                    <ul className="mt-3 space-y-1 text-xs" data-testid={`warnings-${folder.label}`}>
                      {folder.warnings.map((w) =>
                        w.level === "info" ? (
                          <li
                            key={w.text}
                            className="flex items-start gap-1.5 rounded-md border border-border bg-muted/50 px-2 py-1.5 text-muted-foreground"
                          >
                            <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
                            <span>
                              {w.text}
                              {w.link ? (
                                <>
                                  {" "}
                                  <Link
                                    to={w.link.to}
                                    className="relative z-10 text-primary underline underline-offset-2"
                                  >
                                    {w.link.text}
                                  </Link>
                                </>
                              ) : null}
                            </span>
                          </li>
                        ) : (
                          <li
                            key={w.text}
                            className={cn(
                              "flex items-start gap-1.5",
                              w.level === "bad" ? "text-status-bad" : "text-status-warn",
                            )}
                          >
                            <TriangleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
                            {w.text}
                          </li>
                        ),
                      )}
                    </ul>
                  ) : null}
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
          })}
        </div>
      )}
    </div>
  );
}
