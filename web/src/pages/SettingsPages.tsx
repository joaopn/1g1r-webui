import { useMutation } from "@tanstack/react-query";
import { Download, Pin, PinOff, Upload } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { PlatformIcon } from "@/components/PlatformIcon";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError, api, json, upload } from "@/lib/api";
import { formatCount, formatWhen } from "@/lib/format";
import { platformsByName } from "@/lib/platforms";
import { keys, queryClient, useDats, useMeta, useSettingsData } from "@/lib/queries";
import type { DatRow, Meta } from "@/lib/types";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

export function Page({
  title,
  intro,
  children,
}: {
  title: string;
  intro?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="max-w-6xl space-y-6">
      <header>
        <h1 className="font-semibold text-2xl tracking-tight">{title}</h1>
        {intro ? <p className="mt-1 text-muted-foreground text-sm">{intro}</p> : null}
      </header>
      {children}
    </div>
  );
}

export function PlatformsSettingsPage() {
  const meta = useMeta();
  const data = useSettingsData();
  const [ignored, setIgnored] = useState("");
  useEffect(() => {
    if (data.data) setIgnored(data.data.ignored_filenames.join("\n"));
  }, [data.data]);
  const saveTarget = useMutation({
    mutationFn: (targets: Record<string, string>) =>
      api("/settings/targets", json("PUT", { targets })),
    onSuccess: () => {
      toast.success("Target format saved");
      queryClient.invalidateQueries({ queryKey: keys.settings });
      queryClient.invalidateQueries({ queryKey: keys.folders });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const saveIgnored = useMutation({
    mutationFn: () => api("/settings/ignored", json("PUT", { patterns: ignored.split("\n") })),
    onSuccess: () => {
      toast.success("Ignored filenames saved");
      queryClient.invalidateQueries({ queryKey: keys.settings });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  if (!meta.data || !data.data) return <p className="text-muted-foreground">Loading…</p>;
  const targets = data.data.targets;
  return (
    <Page
      title="Platforms & files"
      intro="The target format applies to every folder of that platform."
    >
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="border-border border-b text-left text-muted-foreground text-xs uppercase tracking-wide">
            <tr>
              <th className="px-3 py-2">Platform</th>
              <th className="px-3 py-2">No-Intro DAT</th>
              <th className="px-3 py-2">ROM extensions</th>
              <th className="px-3 py-2">Target format</th>
            </tr>
          </thead>
          <tbody>
            {platformsByName(meta.data.platforms).map(([id, p]) => (
              <tr key={id} className="border-border border-b last:border-b-0 hover:bg-accent/30">
                <td className="px-3 py-2">
                  <span className="flex items-center gap-2">
                    <PlatformIcon platform={p} widthRem={meta.data.ui.platform_icon_width_rem} />{" "}
                    {p.name}
                  </span>
                </td>
                <td className="px-3 py-2 text-muted-foreground">{p.dat_name}</td>
                <td className="px-3 py-2 text-muted-foreground">{p.rom_extensions.join(", ")}</td>
                <td className="px-3 py-2">
                  <select
                    aria-label={`Target format for ${p.name}`}
                    className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                    value={targets[id]}
                    onChange={(event) => saveTarget.mutate({ [id]: event.target.value })}
                  >
                    {p.targets.map((t) => (
                      <option key={t} value={t} title={meta.data?.targets[t]?.description}>
                        {meta.data?.targets[t]?.label ?? t}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <section className="max-w-2xl space-y-2">
        <h2 className="font-semibold text-lg">Ignored filenames</h2>
        <p className="text-muted-foreground text-sm">
          Files matching these patterns (one per line, <code>*</code> wildcards, case-insensitive)
          are never touched or counted as ROMs, in every folder.
        </p>
        <textarea
          aria-label="Ignored filename patterns"
          className="h-48 w-full rounded-md border border-input bg-background p-2 font-mono text-sm"
          value={ignored}
          onChange={(event) => setIgnored(event.target.value)}
        />
        <Button onClick={() => saveIgnored.mutate()}>Save ignored filenames</Button>
      </section>
    </Page>
  );
}

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
    mutationFn: (pinned: boolean) => api(`/dats/${row.platform}/pin`, json("PUT", { pinned })),
    onSuccess: refresh,
    onError,
  });
  const active = row.active;
  const source = active ? meta.dat_sources[active.source] : null;
  return (
    <tr
      className="border-border border-b align-top last:border-b-0 hover:bg-accent/20"
      id={row.platform}
    >
      <td className="px-3 py-2.5">
        <span className="flex items-center gap-2 font-medium">
          <PlatformIcon platform={platform} widthRem={meta.ui.platform_icon_width_rem} />{" "}
          {platform?.name}
        </span>
        {row.folders.length > 0 ? (
          <span className="text-muted-foreground text-xs">folders: {row.folders.join(", ")}</span>
        ) : null}
      </td>
      <td className="px-3 py-2.5">
        {active ? (
          <div className="space-y-1">
            <div>{active.header_name}</div>
            <div className="text-muted-foreground text-xs">
              {source?.label} · version {active.version ?? "?"} · {formatCount(active.game_count)}{" "}
              games · sha1{" "}
              <code title={active.sha1}>{active.sha1.slice(0, meta.ui.hash_display_length)}</code>
            </div>
            <div className="flex flex-wrap gap-1">
              {source?.identification_only ? (
                <Badge variant="outline" className="border-status-warn text-status-warn">
                  identification only
                </Badge>
              ) : null}
              {!active.has_parent_clone && !source?.identification_only ? (
                <Badge variant="outline">no parent/clone</Badge>
              ) : null}
              {!active.matches_platform ? (
                <Badge variant="outline" className="border-status-warn text-status-warn">
                  name differs
                </Badge>
              ) : null}
            </div>
          </div>
        ) : (
          <span className="text-muted-foreground">none</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        {row.versions.length === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <ul className="space-y-1 text-xs">
            {row.versions.map((v) => (
              <li key={v.id} className="flex items-center gap-2">
                {active?.id === v.id ? (
                  <span className="font-medium">
                    ● {meta.dat_sources[v.source]?.label} {v.version ?? ""}
                  </span>
                ) : (
                  <>
                    <span>
                      {meta.dat_sources[v.source]?.label} {v.version ?? ""}
                    </span>
                    <Button
                      variant="link"
                      size="xs"
                      disabled={row.pinned}
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
      </td>
      <td className="px-3 py-2.5">
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
              {d.source === "libretro" ? "libretro" : d.label}
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
          {active ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => pin.mutate(!row.pinned)}
              title={row.pinned ? "Unpin" : "Pin: never switch without unpinning"}
            >
              {row.pinned ? (
                <Pin className="size-3.5" aria-hidden="true" />
              ) : (
                <PinOff className="size-3.5" aria-hidden="true" />
              )}
              {row.pinned ? "pinned" : "pin"}
            </Button>
          ) : null}
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
      </td>
    </tr>
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
      title="DATs"
      intro={
        <>
          Each platform matches against exactly one active DAT, recorded in{" "}
          <code className="text-xs">{data.data?.library_file}</code>. Downloads and uploads are kept
          as versions; a new version is used only when you choose it.
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
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="border-border border-b text-left text-muted-foreground text-xs uppercase tracking-wide">
            <tr>
              <th className="px-3 py-2">Platform</th>
              <th className="px-3 py-2">Active DAT</th>
              <th className="px-3 py-2">Versions</th>
              <th className="px-3 py-2">Get a DAT</th>
            </tr>
          </thead>
          <tbody>
            {[...dats.data]
              .sort((a, b) =>
                (meta.data.platforms[a.platform]?.name ?? a.platform).localeCompare(
                  meta.data.platforms[b.platform]?.name ?? b.platform,
                ),
              )
              .map((row) => (
                <DatRowView key={row.platform} row={row} meta={meta.data} />
              ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}

const SCORE = new Intl.NumberFormat("en-US", { style: "percent" });

export function LookupsSettingsPage() {
  const data = useSettingsData();
  const save = useMutation({
    mutationFn: (change: { hasheous?: boolean; screenscraper?: boolean }) =>
      api("/settings/lookups", json("PUT", change)),
    onSuccess: (_, change) => {
      const [name, on] = Object.entries(change)[0];
      const service = name === "hasheous" ? "Hasheous" : "ScreenScraper";
      toast.success(`${service} lookups ${on ? "on" : "off"}`);
      queryClient.invalidateQueries({ queryKey: keys.settings });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  if (!data.data) return <p className="text-muted-foreground">Loading…</p>;
  const { lookups, hasheous, screenscraper, fuzzy } = data.data;
  return (
    <Page
      title="Online lookups"
      intro="For files the local DAT does not identify. Off until you switch them on; they run during a folder scan."
    >
      <section className="max-w-3xl space-y-3 rounded-lg border border-border bg-card p-4 text-sm">
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
            answers from {hasheous.sources.join(" and ")} for the folder's own platform; others are
            shown, never used
          </dd>
          <dt>Caches</dt>
          <dd>
            every answer; a "not found" is asked again after {hasheous.not_found_ttl_days} days, or
            when you click Look up again on a folder
          </dd>
        </dl>
      </section>
      <section className="max-w-3xl space-y-3 rounded-lg border border-border bg-card p-4 text-sm">
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            className="mt-0.5 size-4 accent-primary"
            checked={lookups.screenscraper}
            disabled={save.isPending || (!screenscraper.configured && !lookups.screenscraper)}
            onChange={(event) => save.mutate({ screenscraper: event.target.checked })}
          />
          <span>
            <span className="font-medium">ScreenScraper</span>{" "}
            <a
              href={screenscraper.site}
              target="_blank"
              rel="noreferrer"
              className="text-muted-foreground underline underline-offset-2"
            >
              {screenscraper.site}
            </a>
            <span className="block text-muted-foreground">
              Asked after Hasheous, for files it did not identify.
            </span>
          </span>
        </label>
        {screenscraper.configured ? null : (
          <p className="text-status-warn" data-testid="screenscraper-credentials">
            Needs credentials in the container's environment (compose):{" "}
            <code className="text-xs">{screenscraper.environment.devid}</code> and{" "}
            <code className="text-xs">{screenscraper.environment.devpassword}</code> (developer),
            optionally <code className="text-xs">{screenscraper.environment.user}</code> and{" "}
            <code className="text-xs">{screenscraper.environment.password}</code> (your account, a
            larger daily quota).
          </p>
        )}
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-muted-foreground">
          <dt>Sends</dt>
          <dd>
            the CRC32, MD5, SHA1 and size of each ROM file still unidentified, and the platform's
            ScreenScraper system; never a file name
          </dd>
          <dt>To</dt>
          <dd>
            <code className="break-all text-xs">{screenscraper.url}</code>
          </dd>
          <dt>Trusts</dt>
          <dd>
            an answer only when the ROM it returns has the file's hash and is named like an entry of
            the folder's DAT; any other name becomes a suggestion
          </dd>
          <dt>Pace</dt>
          <dd>
            one request every {screenscraper.min_interval_seconds} s, stopping for the day near the
            quota ScreenScraper reports
          </dd>
          <dt>Caches</dt>
          <dd>
            every answer; a "not found" is asked again after {screenscraper.not_found_ttl_days} days
          </dd>
        </dl>
      </section>
      <section className="max-w-3xl space-y-2 rounded-lg border border-border bg-card p-4 text-sm">
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
          These values are set in the config file (<code className="text-xs">fuzzy</code>, see
          Advanced).
        </p>
      </section>
    </Page>
  );
}

export function AdvancedSettingsPage() {
  const data = useSettingsData();
  if (!data.data) return <p className="text-muted-foreground">Loading…</p>;
  return (
    <Page
      title="Advanced"
      intro={
        <>
          The configuration in use, for reference. What you set in the UI is kept in{" "}
          <code className="text-xs">{data.data.library_file}</code>; mounts, the port and
          credentials are set in the compose file.
        </>
      }
    >
      <pre className="overflow-x-auto rounded-lg border border-border bg-card p-4 text-xs">
        {data.data.effective_yaml}
      </pre>
    </Page>
  );
}
