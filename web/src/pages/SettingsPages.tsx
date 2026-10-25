import { type QueryKey, useMutation } from "@tanstack/react-query";
import { ChevronRight, Download, ExternalLink, Pin, PinOff, Trash2, Upload } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Box } from "@/components/Box";
import { DatOrderEditor } from "@/components/DatOrderEditor";
import { PlatformIcon } from "@/components/PlatformIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiError, api, json, upload } from "@/lib/api";
import { sourceInfo, titledbFile } from "@/lib/dats";
import { formatCount, formatWhen } from "@/lib/format";
import {
  keys,
  queryClient,
  useDats,
  useMeta,
  useSettingsData,
  useTitledbFiles,
} from "@/lib/queries";
import type { DatRow, Meta } from "@/lib/types";
import { cn } from "@/lib/utils";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

export function Page({
  title,
  intro,
  className,
  children,
}: {
  title: string;
  intro?: ReactNode;
  /** Narrows the centred column, e.g. for a page of text boxes. */
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("mx-auto w-full max-w-6xl space-y-6", className)}>
      <header>
        <h1 className="font-semibold text-2xl tracking-tight">{title}</h1>
        {intro ? <p className="mt-1 text-muted-foreground text-sm">{intro}</p> : null}
      </header>
      {children}
    </div>
  );
}

const HEADING = "mb-1.5 font-medium text-muted-foreground text-xs uppercase tracking-wide";

function DatRowView({ row, meta }: { row: DatRow; meta: Meta }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const platform = meta.platforms[row.platform];
  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.dats });
  const onError = (err: unknown) => toast.error(`${row.platform}: ${errorText(err)}`);
  const download = useMutation({
    mutationFn: (source: string) =>
      api(`/dats/${row.platform}/download?source=${encodeURIComponent(source)}`, {
        method: "POST",
      }),
    onSuccess: (_, source) => {
      const label = row.downloads.find((d) => d.source === source)?.label ?? source;
      toast.success(`${platform?.name}: DAT downloaded from ${label}`);
      refresh();
      queryClient.invalidateQueries({ queryKey: keys.folders });
    },
    onError,
  });
  const send = useMutation({
    mutationFn: (file: File) => api(`/dats/${row.platform}/upload`, upload(file)),
    onSuccess: () => {
      toast.success(`${platform?.name}: DAT uploaded`);
      refresh();
    },
    onError,
  });
  const activate = useMutation({
    mutationFn: (id: number) =>
      api(`/dats/${row.platform}/active`, json("PUT", { version_id: id })),
    onSuccess: () => {
      refresh();
      queryClient.invalidateQueries({ queryKey: keys.folders });
    },
    onError,
  });
  const pin = useMutation({
    mutationFn: ({ source, pinned }: { source: string; pinned: boolean }) =>
      api(`/dats/${row.platform}/pin`, json("PUT", { source, pinned })),
    onSuccess: refresh,
    onError,
  });
  // Each source's active DAT, in the platform's identification order.
  const actives = row.order.filter((e) => e.dat);
  const activeIds = new Set(actives.map((e) => e.dat?.id));
  const summary = actives
    .filter((e) => e.on)
    .map((e) => meta.dat_sources[e.id]?.short_label ?? e.label)
    .join(" → ");
  return (
    <details
      className="group border-border border-b last:border-b-0"
      id={row.platform}
      data-testid={`dats-${row.platform}`}
    >
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-2.5 hover:bg-accent/30 [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90 motion-reduce:transition-none"
          aria-hidden="true"
        />
        <span className="flex w-56 shrink-0 items-center gap-2 font-medium">
          <PlatformIcon platform={platform} widthRem={meta.ui.platform_icon_width_rem} />{" "}
          {platform?.name}
        </span>
        <span className="min-w-0 flex-1 truncate text-muted-foreground text-sm">
          {summary || "no DAT"}
          {row.own_order ? " · own order" : ""}
        </span>
        {row.folders.length > 0 ? (
          <span className="shrink-0 text-muted-foreground text-xs">
            sets: {row.folders.join(", ")}
          </span>
        ) : null}
      </summary>
      <div className="grid gap-4 border-border border-t border-dashed px-4 py-3 text-sm md:grid-cols-[2fr_1.5fr_2fr]">
        <div>
          <h3 className={HEADING}>Active DATs</h3>
          {actives.length > 0 ? (
            <ol className="space-y-2">
              {actives.map((entry, index) => {
                const dat = entry.dat;
                if (!dat) return null;
                const source = sourceInfo(meta, dat.source);
                const titledb = titledbFile(meta, dat.source) !== null;
                return (
                  <li key={entry.id} className={cn("space-y-1", !entry.on && "opacity-60")}>
                    <div>
                      {actives.length > 1 ? (
                        <span className="text-muted-foreground tabular-nums">{index + 1}. </span>
                      ) : null}
                      {dat.header_name}
                      {entry.global_off ? (
                        <Link
                          to="/settings/dat-sources"
                          className="text-status-warn underline underline-offset-2"
                        >
                          {" "}
                          (off for every platform)
                        </Link>
                      ) : !entry.on ? (
                        <span className="text-muted-foreground"> (off)</span>
                      ) : null}
                    </div>
                    <div className="text-muted-foreground text-xs">
                      {source?.label} · version {dat.version ?? "?"} · {formatCount(dat.game_count)}{" "}
                      games · sha1{" "}
                      <code title={dat.sha1}>{dat.sha1.slice(0, meta.ui.hash_display_length)}</code>
                    </div>
                    <div className="flex flex-wrap items-center gap-1">
                      {source?.identification_only ? (
                        <Badge variant="outline" className="border-status-warn text-status-warn">
                          identification only
                        </Badge>
                      ) : null}
                      {!dat.has_parent_clone && !source?.identification_only && !titledb ? (
                        <Badge variant="outline">no parent/clone</Badge>
                      ) : null}
                      {!dat.matches_platform ? (
                        <Badge variant="outline" className="border-status-warn text-status-warn">
                          name differs
                        </Badge>
                      ) : null}
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => pin.mutate({ source: entry.id, pinned: !entry.pinned })}
                        title={
                          entry.pinned
                            ? "Unpin"
                            : "Pin: this source's DAT never switches without unpinning"
                        }
                      >
                        {entry.pinned ? (
                          <Pin className="size-3" aria-hidden="true" />
                        ) : (
                          <PinOff className="size-3" aria-hidden="true" />
                        )}
                        {entry.pinned ? "pinned" : "pin"}
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <span className="text-muted-foreground">none</span>
          )}
          {actives.length > 1 ? (
            <div className="mt-2">
              <DatOrderEditor
                platform={row.platform}
                platformName={platform?.name ?? row.platform}
                entries={row.order}
                own={row.own_order}
                compact
              />
            </div>
          ) : null}
        </div>
        <div>
          <h3 className={HEADING}>Versions</h3>
          {row.versions.length === 0 ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            <ul className="space-y-1 text-xs">
              {row.versions.map((v) => (
                <li key={v.id} className="flex items-center gap-2">
                  {activeIds.has(v.id) ? (
                    <span className="font-medium">
                      ● {sourceInfo(meta, v.source)?.label} {v.version ?? ""}
                    </span>
                  ) : (
                    <>
                      <span>
                        {sourceInfo(meta, v.source)?.label} {v.version ?? ""}
                      </span>
                      <Button
                        variant="link"
                        size="xs"
                        disabled={actives.some((e) => e.id === v.source && e.pinned)}
                        onClick={() => activate.mutate(v.id)}
                      >
                        use
                      </Button>
                    </>
                  )}
                  <span className="text-muted-foreground">{formatWhen(v.added_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className={HEADING}>Get a DAT</h3>
          <div className="flex flex-nowrap gap-1.5 whitespace-nowrap">
            {row.downloads.map((d) => (
              <Button
                key={d.source}
                variant="outline"
                size="sm"
                onClick={() => download.mutate(d.source)}
                disabled={download.isPending}
                title={d.identification_only ? `${d.label} (identification only)` : d.label}
              >
                <Download className="size-3.5" aria-hidden="true" />{" "}
                {d.source === "libretro"
                  ? "libretro"
                  : meta.dat_sources[d.source]?.side
                    ? meta.dat_sources[d.source].short_label
                    : d.label}
              </Button>
            ))}
            {row.pages.map((p) => (
              <Button key={p.source} variant="outline" size="sm" asChild>
                <a
                  href={p.url}
                  target="_blank"
                  rel="noreferrer"
                  title={`${p.label}: download the DAT there, then upload it here`}
                >
                  <ExternalLink className="size-3.5" aria-hidden="true" />{" "}
                  {meta.dat_sources[p.source]?.short_label ?? p.label}
                </a>
              </Button>
            ))}
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInput.current?.click()}
              disabled={send.isPending}
            >
              <Upload className="size-3.5" aria-hidden="true" /> Upload
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept=".dat,.xml,.zip"
              className="hidden"
              aria-label={`DAT file for ${platform?.name}`}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) send.mutate(file);
                event.target.value = "";
              }}
            />
          </div>
          {row.titledb ? <TitledbDownloads row={row} meta={meta} /> : null}
        </div>
      </div>
    </details>
  );
}

/** titledb region files for a title-ID platform: a button for each featured file, any other
 * picked from the list (read from titledb when the list is opened). */
function TitledbDownloads({ row, meta }: { row: DatRow; meta: Meta }) {
  const [picking, setPicking] = useState(false);
  const [chosen, setChosen] = useState("");
  const files = useTitledbFiles(picking);
  const platform = meta.platforms[row.platform];
  const have = new Set(
    row.versions.map((v) => titledbFile(meta, v.source)).filter((f) => f !== null),
  );
  const download = useMutation({
    mutationFn: (file: string) =>
      api(`/dats/${row.platform}/titledb?file=${encodeURIComponent(file)}`, { method: "POST" }),
    onSuccess: (_, file) => {
      toast.success(`${platform?.name}: ${meta.titledb.short_label} ${file} downloaded`);
      queryClient.invalidateQueries({ queryKey: keys.dats });
      queryClient.invalidateQueries({ queryKey: keys.folders });
    },
    onError: (err) => toast.error(`${row.platform}: ${errorText(err)}`),
  });
  const others = (files.data ?? []).filter((f) => !meta.titledb.featured.includes(f));
  const hint = (file: string) =>
    have.has(file)
      ? `${file} is downloaded: again for a newer version (used once you choose it under Versions)`
      : `Download ${file}`;
  return (
    <div className="mt-3" data-testid={`titledb-${row.platform}`}>
      <h3 className={HEADING}>Names from titledb</h3>
      <p className="mb-1.5 text-muted-foreground text-xs">
        Names, publishers and release dates by title ID, one file per eShop region. The first file
        in the order listing a game names it. Source:{" "}
        <a className="underline" href={meta.titledb.website} target="_blank" rel="noreferrer">
          {meta.titledb.label}
        </a>
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        {meta.titledb.featured.map((file) => (
          <Button
            key={file}
            variant="outline"
            size="sm"
            onClick={() => download.mutate(file)}
            disabled={download.isPending}
            title={hint(file)}
          >
            <Download className="size-3.5" aria-hidden="true" /> {file}
          </Button>
        ))}
      </div>
      <div className="mt-1.5 flex flex-nowrap items-center gap-1.5">
        <select
          aria-label={`Another ${meta.titledb.short_label} file for ${platform?.name}`}
          className="h-8 rounded-md border border-input bg-background px-2 text-sm"
          value={chosen}
          onFocus={() => setPicking(true)}
          onPointerDown={() => setPicking(true)}
          onChange={(event) => setChosen(event.target.value)}
        >
          <option value="">
            {files.isFetching ? "Loading…" : files.isError ? "List unavailable" : "Other region…"}
          </option>
          {others.map((file) => (
            <option key={file} value={file} title={hint(file)}>
              {file}
            </option>
          ))}
        </select>
        <Button
          variant="outline"
          size="sm"
          onClick={() => download.mutate(chosen)}
          disabled={!chosen || download.isPending}
          aria-label={chosen ? `Download ${chosen}` : "Download the chosen file"}
        >
          <Download className="size-3.5" aria-hidden="true" /> Download
        </Button>
        {download.isPending ? (
          <span className="text-muted-foreground text-xs">Downloading {download.variables}…</span>
        ) : null}
      </div>
    </div>
  );
}

export function DatsSettingsPage() {
  const meta = useMeta();
  const dats = useDats();
  const data = useSettingsData();
  const packInput = useRef<HTMLInputElement>(null);
  const pack = useMutation({
    mutationFn: (file: File) =>
      api<{ platform: string | null; version_id: number | null }[]>("/dats/pack", upload(file)),
    onSuccess: (results) => {
      const added = results.filter((r) => r.version_id);
      toast.success(`Pack: ${added.length} DATs added, ${results.length - added.length} skipped`);
      queryClient.invalidateQueries({ queryKey: keys.dats });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  if (!meta.data || !dats.data) return <p className="text-muted-foreground">Loading…</p>;
  return (
    <Page
      title="Platform DATs"
      intro={
        <>
          The DATs each platform has: one active version per source, recorded in{" "}
          <code className="text-xs">{data.data?.library_file}</code>. Downloads and uploads are kept
          as versions; the first of a source is used at once, a newer one only when you choose it.
          The order is each platform's own (DAT order); sources switched off for every platform:{" "}
          <Link to="/settings/dat-sources" className="underline underline-offset-2">
            Which DATs to use?
          </Link>
        </>
      }
    >
      <section className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-sm">
        <span>
          <strong>No-Intro daily pack</strong>{" "}
          <span className="text-muted-foreground">
            — download it from{" "}
            <a
              className="text-primary underline"
              href={meta.data.dat_sources.nointro?.website}
              target="_blank"
              rel="noreferrer"
            >
              DAT-o-MATIC
            </a>{" "}
            (Standard DAT), then upload the zip; it is split by platform.
          </span>
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={() => packInput.current?.click()}
          disabled={pack.isPending}
        >
          <Upload className="size-3.5" aria-hidden="true" /> Upload pack
        </Button>
        <input
          ref={packInput}
          type="file"
          accept=".zip"
          className="hidden"
          aria-label="No-Intro daily pack zip"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) pack.mutate(file);
            event.target.value = "";
          }}
        />
      </section>
      <div className="rounded-lg border border-border bg-card">
        {[...dats.data]
          .sort((a, b) =>
            (meta.data.platforms[a.platform]?.name ?? a.platform).localeCompare(
              meta.data.platforms[b.platform]?.name ?? b.platform,
            ),
          )
          .map((row) => (
            <DatRowView key={row.platform} row={row} meta={meta.data} />
          ))}
      </div>
      <RemoveDatsBox rows={dats.data} meta={meta.data} />
    </Page>
  );
}

const datCount = (count: number) => `${formatCount(count)} ${count === 1 ? "DAT" : "DATs"}`;
const platformCount = (count: number) =>
  `${formatCount(count)} ${count === 1 ? "platform" : "platforms"}`;

/** One button per source with stored DATs: removes all of them, on every platform. */
function RemoveDatsBox({ rows, meta }: { rows: DatRow[]; meta: Meta }) {
  const [removing, setRemoving] = useState<string | null>(null);
  // titledb's region files are one source here.
  const sourceOf = (source: string) =>
    titledbFile(meta, source) === null ? source : meta.titledb.short_label;
  const sources: [string, { label: string; short_label: string }][] = [
    ...Object.entries(meta.dat_sources),
    [meta.titledb.short_label, meta.titledb],
  ];
  const stored = sources
    .map(([id, source]) => {
      const mine = (r: DatRow) => r.versions.filter((v) => sourceOf(v.source) === id);
      const having = rows.filter((r) => mine(r).length > 0);
      const count = rows.reduce((sum, r) => sum + mine(r).length, 0);
      return { id, label: source.label, short: source.short_label, count, platforms: having };
    })
    .filter((s) => s.count > 0);
  const chosen = stored.find((s) => s.id === removing);
  const remove = useMutation({
    mutationFn: (source: string) =>
      api<{ versions: number; platforms: string[] }>(`/dats/sources/${source}`, {
        method: "DELETE",
      }),
    onSuccess: (result, source) => {
      toast.success(
        `Removed ${datCount(result.versions)} (${stored.find((s) => s.id === source)?.short})`,
      );
      setRemoving(null);
      queryClient.invalidateQueries({ queryKey: keys.dats });
      queryClient.invalidateQueries({ queryKey: keys.folders });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <Box title="Remove DATs">
      {stored.length === 0 ? (
        <p className="text-muted-foreground">No DATs stored.</p>
      ) : (
        <>
          <p className="text-muted-foreground">
            Removes every DAT of a source, on every platform, versions and files included.
          </p>
          <div className="flex flex-wrap gap-2 pt-2">
            {stored.map((s) => (
              <Button key={s.id} variant="outline" size="sm" onClick={() => setRemoving(s.id)}>
                <Trash2 className="size-3.5" aria-hidden="true" /> {s.short}
                <span className="text-muted-foreground">· {datCount(s.count)}</span>
              </Button>
            ))}
          </div>
        </>
      )}
      <Dialog
        open={chosen !== undefined}
        onOpenChange={(open) => (open ? null : setRemoving(null))}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove every {chosen?.label} DAT?</DialogTitle>
            <DialogDescription>
              {chosen ? datCount(chosen.count) : null} on{" "}
              {chosen ? platformCount(chosen.platforms.length) : null} (
              {chosen?.platforms
                .map((r) => meta.platforms[r.platform]?.name ?? r.platform)
                .sort()
                .join(", ")}
              ) are deleted, files included. Sets keep their matches until their next scan; a
              platform left without a DAT matches no checksums until you add one.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoving(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => chosen && remove.mutate(chosen.id)}
            >
              Remove {chosen ? datCount(chosen.count) : null}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Box>
  );
}

const SCORE = new Intl.NumberFormat("en-US", { style: "percent" });

export function LookupsSettingsPage() {
  const data = useSettingsData();
  const save = useMutation({
    mutationFn: (change: { hasheous: boolean }) => api("/settings/lookups", json("PUT", change)),
    onSuccess: (_, change) => {
      toast.success(`Hasheous lookups ${change.hasheous ? "on" : "off"}`);
      queryClient.invalidateQueries({ queryKey: keys.settings });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  if (!data.data) return <p className="text-muted-foreground">Loading…</p>;
  const { lookups, hasheous, fuzzy } = data.data;
  return (
    <Page
      title="Online lookups"
      className="max-w-3xl"
      intro="For files no DAT identifies. Off until you switch it on; it runs during a scan, at its place in the DAT order."
    >
      <section className="space-y-3 rounded-lg border border-border bg-card p-4 text-sm">
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            className="mt-0.5 size-4 accent-primary"
            checked={lookups.hasheous}
            disabled={save.isPending}
            onChange={(event) => save.mutate({ hasheous: event.target.checked })}
          />
          <span>
            <span className="font-medium">Hasheous</span>{" "}
            <a
              href={hasheous.site}
              target="_blank"
              rel="noreferrer"
              className="text-muted-foreground underline underline-offset-2"
            >
              {hasheous.site}
            </a>
          </span>
        </label>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-muted-foreground">
          <dt>Sends</dt>
          <dd>
            the CRC32, MD5 and SHA1 of each ROM file the local DAT did not identify; no file names,
            no file contents, nothing else
          </dd>
          <dt>To</dt>
          <dd>
            <code className="break-all text-xs">{hasheous.url}</code>
          </dd>
          <dt>Trusts</dt>
          <dd>
            answers for the folder's own platform: from {hasheous.sources.join(" and ")}, their
            name; from {hasheous.other_sources.join(", ")}, only a name one of the platform's DATs
            lists, their other names becoming suggestions. Answers for other platforms are shown,
            never used
          </dd>
          <dt>Caches</dt>
          <dd>
            every answer; a "not found" is asked again after {hasheous.not_found_ttl_days} days, or
            when you click Look up again on a folder
          </dd>
        </dl>
      </section>
      <section className="space-y-2 rounded-lg border border-border bg-card p-4 text-sm">
        <h2 className="font-medium">Name suggestions</h2>
        <p className="text-muted-foreground">
          Files still unmatched get up to {fuzzy.max_suggestions} DAT names that look like theirs,
          scoring at least {SCORE.format(fuzzy.min_score)}.{" "}
          {fuzzy.auto_match_threshold === null ? (
            <>
              They never identify a file: auto-match is <strong>off</strong>.
            </>
          ) : (
            <>
              They identify a file only when the best scores at least{" "}
              <strong>{SCORE.format(fuzzy.auto_match_threshold)}</strong> (auto-match).
            </>
          )}{" "}
          These values are the app's built-in defaults (<code className="text-xs">fuzzy</code>,
          shown in Advanced).
        </p>
      </section>
    </Page>
  );
}

/** A whole number set in Advanced, saved to the library; null goes back to the default. */
function NumberSetting({
  title,
  label,
  path,
  saved,
  value,
  current,
  isDefault,
  max,
  invalidates = [],
  children,
}: {
  title: string;
  label: string;
  path: string;
  saved: string;
  /** Shown in the field. */
  value: number;
  /** What is saved (null: the default); Save is off while the field equals it. */
  current: number | null;
  isDefault: boolean;
  max: number;
  /** Queries refreshed after a save besides the settings (what the value changes). */
  invalidates?: readonly QueryKey[];
  children: ReactNode;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const save = useMutation({
    mutationFn: (chosen: number | null) => api(path, json("PUT", { value: chosen })),
    onSuccess: () => {
      toast.success(saved);
      queryClient.invalidateQueries({ queryKey: keys.settings });
      for (const queryKey of invalidates) queryClient.invalidateQueries({ queryKey });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const chosen = Number(draft);
  const valid = Number.isInteger(chosen) && chosen >= 1 && chosen <= max;
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-4 text-sm">
      <h2 className="font-medium">{title}</h2>
      <p className="text-muted-foreground">{children}</p>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="number"
          aria-label={label}
          min={1}
          max={max}
          className="h-8 w-20 rounded-md border border-input bg-background px-2 text-sm"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button
          size="sm"
          aria-label={`Save ${label.toLowerCase()}`}
          disabled={!valid || chosen === current || save.isPending}
          onClick={() => save.mutate(chosen)}
        >
          Save
        </Button>
        {isDefault ? null : (
          <Button
            size="sm"
            variant="outline"
            disabled={save.isPending}
            onClick={() => save.mutate(null)}
          >
            Use the default
          </Button>
        )}
      </div>
    </section>
  );
}

export function AdvancedSettingsPage() {
  const data = useSettingsData();
  if (!data.data) return <p className="text-muted-foreground">Loading…</p>;
  const parallel = data.data.parallel_scans;
  const conversions = data.data.parallel_conversions;
  const threads = data.data.igir_threads;
  const rows = data.data.page_size;
  return (
    <Page
      title="Advanced"
      className="max-w-3xl"
      intro={
        <>
          The configuration in use, for reference. What you set in the UI is kept in{" "}
          <code className="text-xs">{data.data.library_file}</code>; mounts, the port and
          credentials are set in the compose file.
        </>
      }
    >
      <NumberSetting
        title="Parallel scans"
        label="Parallel scans"
        path="/settings/parallel-scans"
        saved="Parallel scans saved"
        value={parallel.value}
        current={parallel.value}
        isDefault={parallel.value === parallel.default}
        max={parallel.max}
      >
        How many folders are scanned at a time; further scans wait in line. Applies (moves,
        conversions, restores) run one at a time, apart from scans. Default {parallel.default}, at
        most {parallel.max}.
      </NumberSetting>
      <NumberSetting
        title="Parallel conversions"
        label="Parallel conversions"
        path="/settings/parallel-conversions"
        saved="Parallel conversions saved"
        value={conversions.value}
        current={conversions.value}
        isDefault={conversions.value === conversions.default}
        max={conversions.max}
      >
        How many files a conversion run converts at a time, each from unpacking to moving its
        original. Unpacked copies are deleted as soon as the output is written. Default{" "}
        {conversions.default}, at most {conversions.max}. Applies from the next run.
      </NumberSetting>
      <NumberSetting
        title="Rows per page"
        label="Rows per page"
        path="/settings/page-size"
        saved="Rows per page saved"
        value={rows.value}
        current={rows.value}
        isDefault={rows.value === rows.default}
        max={rows.max}
        invalidates={[keys.meta]}
      >
        How many rows a table shows before the next page (games on the Matching table). Default{" "}
        {rows.default}, at most {rows.max}.
      </NumberSetting>
      <NumberSetting
        title="igir threads per scan"
        label="igir threads"
        path="/settings/igir-threads"
        saved="igir threads saved"
        value={threads.value ?? threads.default_readers}
        current={threads.value}
        isDefault={threads.value === null}
        max={threads.max}
      >
        How many files one igir run reads at once, and the size of its pool for reading and decoding
        CHDs. Checksumming itself runs on one thread per run, so more threads mostly help with fast
        disks; fewer keep a busy machine responsive. Default: igir&apos;s own (
        {threads.default_readers} files at once, a pool of {threads.default_pool}), at most{" "}
        {threads.max}. Applies from the next scan.
      </NumberSetting>
      <pre className="overflow-x-auto rounded-lg border border-border bg-card p-4 text-xs">
        {data.data.effective_yaml}
      </pre>
    </Page>
  );
}
