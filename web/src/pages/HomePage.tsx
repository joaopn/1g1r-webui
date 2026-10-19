import { useMutation } from "@tanstack/react-query";
import { Download, Info, RefreshCw, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { PlatformIcon } from "@/components/PlatformIcon";
import { Button } from "@/components/ui/button";
import { ApiError, api } from "@/lib/api";
import { formatBytes, formatCount, formatFiles, formatWhen } from "@/lib/format";
import { foldersByName } from "@/lib/platforms";
import { invalidateFolder, useFolders, useMeta } from "@/lib/queries";
import { scanProgress, useStartScan } from "@/lib/scan";
import type { FolderCard, Scan } from "@/lib/types";
import { cn } from "@/lib/utils";

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
  if (!meta.data || !folders.data) return <p className="text-muted-foreground">Loading…</p>;
  const ui = meta.data.ui;
  const shown = folders.data.filter((f) => !f.hidden);
  const hidden = folders.data.length - shown.length;
  return (
    <div className="space-y-6">
      <header>
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
      </header>
      {shown.length === 0 ? (
        <div className="max-w-xl rounded-lg border border-border bg-card p-6">
          <h2 className="font-medium">No sets yet</h2>
          <p className="mt-1 text-muted-foreground text-sm">
            Add a platform folder with <strong>Add set</strong> at the bottom of the sidebar, or a
            folder holding one folder per platform with <strong>Add sets from a folder</strong>.
            Each set holds exactly one platform.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(20rem,1fr))] gap-4">
          {foldersByName(shown, meta.data.platforms).map((folder) => {
            const platform = meta.data.platforms[folder.platform];
            const stats = [
              {
                label: "identified",
                value: `${formatCount(folder.summary.identified)} / ${formatCount(folder.summary.roms)}`,
              },
              {
                label: "unmatched",
                value: formatCount(folder.summary.unmatched),
                attention: folder.summary.unmatched > 0,
              },
              {
                label: "games with several versions",
                value: formatCount(folder.counts.several ?? 0),
              },
              {
                label: "undecided",
                value: formatCount(folder.counts.undecided ?? 0),
                attention: (folder.counts.undecided ?? 0) > 0,
              },
              { label: "proposed moves", value: formatCount(folder.counts.proposals ?? 0) },
              {
                label: "to convert",
                value: formatCount(folder.conversion.to_convert),
                attention: folder.conversion.to_convert > 0,
              },
              {
                label: "conversions flagged",
                value: formatCount(folder.conversion.flagged),
                attention: folder.conversion.flagged > 0,
              },
              {
                label: "would free",
                value: formatBytes(folder.reclaim_bytes, ui.byte_unit_base, ui.byte_units),
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
              },
            ];
            const progress = scanProgress(folder.scan);
            return (
              <div
                key={folder.label}
                className="group relative overflow-hidden rounded-lg border border-border bg-card transition-colors hover:border-primary/50 hover:bg-accent/30"
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
                      <Link
                        to={`/folders/${folder.label}/matching`}
                        className="after:absolute after:inset-0 after:content-['']"
                      >
                        {platform?.name ?? folder.platform}
                      </Link>
                    </h2>
                    <span className="shrink-0 text-muted-foreground text-sm">{folder.label}</span>
                  </div>
                  <p className="mt-1 truncate text-muted-foreground text-xs">
                    {folder.location ?? `mount ${folder.mount} unavailable`}
                  </p>
                  <p className="mt-2 text-xs">
                    {folder.dat ? (
                      `DAT ${folder.dat.header_name} · ${folder.dat.version ?? "?"}`
                    ) : (
                      <span className="text-status-warn">No DAT yet</span>
                    )}
                    <br />
                    {folder.scan ? (
                      folder.scan.status === "done" ? (
                        `Scanned ${formatWhen(folder.scan.finished_at)}`
                      ) : progress ? (
                        <span data-testid={`scan-status-${folder.label}`}>{progress.text}</span>
                      ) : (
                        <span className="text-status-bad">Last scan failed</span>
                      )
                    ) : (
                      <span className="text-muted-foreground">Not scanned yet</span>
                    )}
                  </p>
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
                        <div key={s.label}>
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
