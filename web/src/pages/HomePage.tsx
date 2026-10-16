import { Link } from "react-router-dom";
import { PlatformIcon } from "@/components/PlatformIcon";
import { formatBytes, formatCount, formatWhen } from "@/lib/format";
import { foldersByName } from "@/lib/platforms";
import { useFolders, useMeta } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function HomePage() {
  const meta = useMeta();
  const folders = useFolders();
  if (!meta.data || !folders.data) return <p className="text-muted-foreground">Loading…</p>;
  const ui = meta.data.ui;
  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-semibold text-2xl tracking-tight">Home</h1>
        <p className="text-muted-foreground text-sm">
          Read-only build: everything here is a proposal. Nothing in your ROM folders is changed.
        </p>
      </header>
      {folders.data.length === 0 ? (
        <div className="max-w-xl rounded-lg border border-border bg-card p-6">
          <h2 className="font-medium">No platforms yet</h2>
          <p className="mt-1 text-muted-foreground text-sm">
            Add a platform folder with <strong>Add platform</strong> at the bottom of the sidebar.
            Each folder holds exactly one platform.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(20rem,1fr))] gap-4">
          {foldersByName(folders.data, meta.data.platforms).map((folder) => {
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
            ];
            return (
              <Link
                key={folder.label}
                to={`/folders/${folder.label}/matching`}
                className="group rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/50 hover:bg-accent/30"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <PlatformIcon platform={platform} />
                  <h2
                    className="min-w-0 truncate font-medium group-hover:text-primary"
                    title={platform?.name ?? folder.platform}
                  >
                    {platform?.name ?? folder.platform}
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
                    ) : folder.scan.status === "running" ? (
                      "Scanning…"
                    ) : (
                      <span className="text-status-bad">Last scan failed</span>
                    )
                  ) : (
                    <span className="text-muted-foreground">Not scanned yet</span>
                  )}
                </p>
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
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
