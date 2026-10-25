import { useMutation } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { PlatformIcon } from "@/components/PlatformIcon";
import { ApiError, api, json } from "@/lib/api";
import { keys, queryClient, useDatSources, useDats, useMeta, useSettingsData } from "@/lib/queries";
import type { DatSource } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Page } from "@/pages/SettingsPages";

type Guide = {
  what: ReactNode;
  pros: string[];
  cons: string[];
  /** What a platform's DAT is, where the platform names none. */
  files?: string;
};

/** What each source is good and bad at, for choosing the order. */
const GUIDE: Record<string, Guide> = {
  nointro: {
    what: "No-Intro's own DATs (DAT-o-MATIC): cartridge and digital releases.",
    pros: [
      "Lists every file of a game: multi-disk games kept in one archive match",
      "Parent/clone data: versions group reliably",
      "The reference names for cartridge platforms",
    ],
    cons: ["Downloaded by hand from DAT-o-MATIC, then uploaded (one platform or the daily pack)"],
  },
  upload: {
    what: "Any other DAT you upload for a platform.",
    pros: ["Anything in Logiqx or ClrMamePro format: a set's own DAT, a newer or older release"],
    cons: ["Kept up to date by you", "As good as where it came from"],
  },
  redump: {
    what: "Redump's DATs (redump.info): disc platforms.",
    pros: ["One-click download", "Whole discs (every track), with serials and parent/clone data"],
    cons: ["Disc platforms only"],
  },
  nonredump: {
    what: "No-Intro's Non-Redump DATs (DAT-o-MATIC): discs Redump does not list.",
    pros: [
      "Prototypes, betas, unlicensed and homebrew discs",
      "Its names are suggestions and manual matches for files no checksum identifies",
    ],
    cons: [
      "Downloaded by hand from DAT-o-MATIC (a button on Platform DATs opens the page), then uploaded",
      "Many entries are unverified dumps: a different build of the same disc does not match by checksum",
    ],
  },
  psn: {
    what: "No-Intro's PSN DATs, from libretro's mirror: digital-only releases (PSP).",
    pros: ["One-click download", "Games sold only on PSN, each a decrypted image like a disc dump"],
    cons: [
      "No parent/clone data (identification only)",
      "Games kept as an EBOOT.PBP folder (minis) are not a supported format",
    ],
  },
  fbneo: {
    what: "FinalBurn Neo's DATs: arcade romsets.",
    pros: ["One-click download", "Parent/clone and BIOS data for romsets built for FBNeo"],
    cons: ["Arcade only", "Matches sets built for FinalBurn Neo, not for MAME"],
  },
  libretro: {
    what: "libretro's mirror of No-Intro, in its game database.",
    pros: ["One-click download for every cartridge platform"],
    cons: [
      "One file per game: a game kept whole in one archive (several disks) does not match, and a lone disk matches as the game (marked incomplete)",
      "No parent/clone data (identification only): versions group by Retool's clone lists and names",
    ],
  },
  tosec: {
    what: "TOSEC: computers and everything else, in many formats.",
    pros: ["Covers what No-Intro does not (Amiga ADF, C64 tapes and disks, many alternate dumps)"],
    cons: [
      "One large pack download (about 100 MB, every system)",
      "Its own naming: never joined with No-Intro names, so a game in both stays two games",
      "No parent/clone data",
    ],
  },
  hasheous: {
    what: "Hasheous: an online checksum database gathering No-Intro, Redump, TOSEC, RetroAchievements, MAME software lists and more.",
    pros: [
      "Identifies files no DAT here lists, by checksum, without an account",
      "Names from its other sources become suggestions when no DAT lists them",
    ],
    cons: [
      "Sends checksums (never files or names) over the internet",
      "Skips archives with several ROM files",
    ],
  },
  titledb: {
    what: "titledb (blawar/titledb): Switch names, publishers and release dates by title ID, one file per eShop region.",
    pros: [
      "One-click download per region",
      "Names every base game, update and DLC by its title ID: no checksum DAT exists for Switch",
    ],
    cons: [
      "Names only: checksums are not checked",
      "A region file lists only what that eShop sold",
    ],
    files: "One file per eShop region (US.en, JP.ja, …)",
  },
};

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

const TABS = [
  { id: "multi", label: "Multiplatform" },
  { id: "single", label: "Single platform" },
] as const;
type Tab = (typeof TABS)[number]["id"];

const TH = "px-3 py-2";
const TD = "px-3 py-2.5";

/** What a source is, and what it is good and bad at. */
function SourceText({ source }: { source: DatSource }) {
  const guide = GUIDE[source.id];
  return (
    <>
      <div className="font-medium">{source.label}</div>
      <div className="text-muted-foreground text-xs">{guide?.what}</div>
    </>
  );
}

function Bullets({ items }: { items: string[] | undefined }) {
  return (
    <ul className="list-disc space-y-0.5 pl-4 text-xs">
      {items?.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

/** The source's switch for every platform; online lookups are switched in Online lookups. */
function UseCell({
  source,
  lookupsOn,
  onToggle,
  busy,
}: {
  source: DatSource;
  lookupsOn: Record<string, boolean> | undefined;
  onToggle: (source: DatSource) => void;
  busy: boolean;
}) {
  if (source.lookup) {
    const on = lookupsOn?.[source.id] ?? false;
    return (
      <Link
        to="/settings/lookups"
        className={cn("text-xs underline underline-offset-2", !on && "text-status-warn")}
      >
        {on ? "on" : "off"} in Online lookups
      </Link>
    );
  }
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        className="size-3.5 accent-primary"
        checked={source.on}
        disabled={busy}
        onChange={() => onToggle(source)}
        aria-label={`Use ${source.label}`}
      />
      {source.on ? "on" : "off"}
    </label>
  );
}

/** Which DAT sources and lookups there are, what each is good for, and the switch that turns
 * one off on every platform. Each platform's order is on Platform DATs. */
export function DatSourcesPage() {
  const meta = useMeta();
  const sources = useDatSources();
  const settings = useSettingsData();
  const dats = useDats();
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get("tab") === "single" ? "single" : "multi";
  const [allPlatforms, setAllPlatforms] = useState(false);
  const save = useMutation({
    mutationFn: (off: string[]) => api<DatSource[]>("/dat-sources", json("PUT", { off })),
    onSuccess: (saved) => {
      toast.success("Saved; scan a set to use it");
      queryClient.setQueryData(keys.datSources, saved);
      queryClient.invalidateQueries({ queryKey: keys.dats });
      queryClient.invalidateQueries({ queryKey: keys.folders });
      queryClient.invalidateQueries({ queryKey: ["folder"] });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const toggle = (source: DatSource) =>
    save.mutate(
      (sources.data ?? [])
        .filter((s) => !s.lookup && (s.id === source.id ? s.on : !s.on))
        .map((s) => s.id),
    );
  const lookupsOn = settings.data?.lookups as Record<string, boolean> | undefined;
  const platforms = meta.data?.platforms ?? {};
  const withSets = new Set(
    (dats.data ?? []).filter((r) => r.folders.length > 0).map((r) => r.platform),
  );
  const byName = (a: string, b: string) =>
    (platforms[a]?.name ?? a).localeCompare(platforms[b]?.name ?? b);
  const multi = (sources.data ?? []).filter((s) => !s.side);
  const single = (sources.data ?? []).filter((s) => s.side);

  return (
    <Page
      title="Which DATs to use?"
      intro={
        <>
          A DAT lists every known dump of a platform's games with its checksums. A platform
          identifies its files with the sources it has a DAT from, each trying the files the ones
          before it did not identify, in the platform's order (
          <Link to="/settings/dats" className="underline underline-offset-2">
            Platform DATs
          </Link>
          , or DAT order on a Matching page). A source switched off here is off on every platform.
        </>
      }
    >
      <div
        role="tablist"
        aria-label="Sources"
        className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={t.id === tab}
            onClick={() => setParams(t.id === "multi" ? {} : { tab: t.id }, { replace: true })}
            className={cn(
              "rounded-md px-3 py-2 font-medium text-sm transition-colors",
              t.id === tab
                ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "multi" ? (
        <div className="overflow-x-auto rounded-lg border border-border bg-card" role="tabpanel">
          <table className="w-full text-sm">
            <thead className="border-border border-b text-left text-muted-foreground text-xs uppercase tracking-wide">
              <tr>
                <th className={TH}>Source</th>
                <th className={TH}>Good</th>
                <th className={TH}>Less good</th>
                <th className={TH}>Platforms</th>
                <th className={TH}>Use</th>
              </tr>
            </thead>
            <tbody>
              {multi.map((source) => (
                <tr
                  key={source.id}
                  className={cn(
                    "border-border border-b align-top last:border-b-0",
                    !source.lookup && !source.on && "text-muted-foreground",
                  )}
                  data-testid={`source-${source.id}`}
                >
                  <td className={cn(TD, "max-w-64")}>
                    <SourceText source={source} />
                  </td>
                  <td className={TD}>
                    <Bullets items={GUIDE[source.id]?.pros} />
                  </td>
                  <td className={TD}>
                    <Bullets items={GUIDE[source.id]?.cons} />
                  </td>
                  <td className={cn(TD, "w-80")} data-testid={`platforms-${source.id}`}>
                    {source.every ? (
                      <span className="text-muted-foreground text-xs">Every platform</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {source.platforms
                          .map((p) => p.platform)
                          .sort(byName)
                          .map((id) => (
                            <span key={id} title={platforms[id]?.name ?? id}>
                              <PlatformIcon platform={platforms[id]} />
                            </span>
                          ))}
                      </div>
                    )}
                  </td>
                  <td className={TD}>
                    <UseCell
                      source={source}
                      lookupsOn={lookupsOn}
                      onToggle={toggle}
                      busy={save.isPending}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="space-y-4" role="tabpanel">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-3.5 accent-primary"
              checked={allPlatforms}
              onChange={() => setAllPlatforms(!allPlatforms)}
            />
            All platforms{" "}
            <span className="text-muted-foreground">(else only those with a set)</span>
          </label>
          {single.map((source) => {
            const shown = source.platforms
              .filter((p) => allPlatforms || withSets.has(p.platform))
              .sort((a, b) => byName(a.platform, b.platform));
            return (
              <section
                key={source.id}
                className={cn(
                  "rounded-lg border border-border bg-card text-sm",
                  !source.on && "text-muted-foreground",
                )}
                data-testid={`source-${source.id}`}
              >
                <div className="grid items-start gap-3 border-border border-b px-3 py-2.5 md:grid-cols-[16rem_1fr_1fr_auto]">
                  <div>
                    <SourceText source={source} />
                  </div>
                  <Bullets items={GUIDE[source.id]?.pros} />
                  <Bullets items={GUIDE[source.id]?.cons} />
                  <UseCell
                    source={source}
                    lookupsOn={lookupsOn}
                    onToggle={toggle}
                    busy={save.isPending}
                  />
                </div>
                {shown.length === 0 ? (
                  <p className="px-3 py-2 text-muted-foreground text-xs">
                    No set of a platform it serves.
                  </p>
                ) : (
                  <table className="w-full">
                    <thead className="text-left text-muted-foreground text-xs uppercase tracking-wide">
                      <tr>
                        <th className={cn(TH, "w-64")}>Platform</th>
                        <th className={TH}>DAT</th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.map((p) => (
                        <tr key={p.platform} className="border-border border-t">
                          <td className={TD}>
                            <span className="flex items-center gap-2">
                              <PlatformIcon
                                platform={platforms[p.platform]}
                                widthRem={meta.data?.ui.platform_icon_width_rem}
                              />
                              {platforms[p.platform]?.name ?? p.platform}
                            </span>
                          </td>
                          <td className={cn(TD, "text-muted-foreground")}>
                            {p.dat_name ?? GUIDE[source.id]?.files ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
            );
          })}
        </div>
      )}
      <Faq />
    </Page>
  );
}

/** Questions asked while choosing DATs, answered. */
const FAQ: { q: string; a: ReactNode }[] = [
  {
    q: "What is the difference between No-Intro (DAT-o-MATIC) and the libretro-database mirror?",
    a: (
      <>
        <p>
          Same DATs, same people. No-Intro catalogues cartridge and digital dumps; DAT-o-MATIC is
          their website, where the original DATs are downloaded. libretro-database is a GitHub
          repository kept by the RetroArch team with copies of those DATs, cut down for RetroArch's
          own scanner. Both name games the same way.
        </p>
        <p>
          The copy is one click away, but it often keeps one file per game (a multi-disk game in one
          archive does not match it) and drops the parent/clone links. For most cartridge platforms,
          one file per game, it works as well; for Amiga or C64, upload No-Intro's.
        </p>
      </>
    ),
  },
  {
    q: 'What does "identification only" mean?',
    a: (
      <p>
        The DAT has no parent/clone links. It identifies files as well as any other, but cannot say
        which games are versions of each other, so grouping falls back to Retool's clone lists and
        to the DAT names.
      </p>
    ),
  },
  {
    q: "How are DATs used, exactly?",
    a: (
      <ol className="list-decimal space-y-1 pl-4">
        <li>
          <strong>Matching</strong>: each file's checksums are compared with the DATs, in the
          platform's order. igir matches a multi-file game only when every file the DAT lists is in
          the archive. The file gets the DAT's game name; its own file name plays no part.
        </li>
        <li>
          <strong>Grouping</strong>: the DAT's parent/clone links say which names are versions of
          one game. Without them, Retool's clone lists (kept by hand against No-Intro names), then
          the DAT names with region, language and revision removed; a tag that tells games apart is
          kept, so different games are never joined.
        </li>
        <li>
          <strong>Ranking</strong>: the tags in each DAT name (region, languages, revision,
          pre-release, TOSEC dump flags) decide which version is kept.
        </li>
      </ol>
    ),
  },
  {
    q: "So libretro only differs in files per game and grouping?",
    a: (
      <p>
        Yes. Matching is by checksum with either. The missing parent/clone links only change how
        versions are grouped, through Retool and names instead. Once a No-Intro DAT is in a
        platform's order, its links also cover the names libretro identified, since the names are
        the same.
      </p>
    ),
  },
  {
    q: "What happens to one disk of a game that another DAT lists whole?",
    a: (
      <p>
        libretro may list only Disk 2 of a game, so a loose Disk 2 file matches it as the game,
        while No-Intro matches the archive holding every disk. Both become versions of one game; the
        lone disk is marked incomplete and is never kept over the whole one.
      </p>
    ),
  },
  {
    q: "Does a quick scan skip the DATs?",
    a: (
      <p>
        No. What a scan reads from each file (archive contents, headers, checksums) is the same
        whatever the DAT, so a quick scan reuses it for unchanged files. Matching against the DATs,
        in their current order, runs on every scan.
      </p>
    ),
  },
];

function Faq() {
  return (
    <details className="group rounded-lg border border-border bg-card" data-testid="dat-faq">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight
          className="size-4 text-muted-foreground transition-transform group-open:rotate-90 motion-reduce:transition-none"
          aria-hidden="true"
        />
        Questions and answers
      </summary>
      <dl className="space-y-4 border-border border-t px-4 py-3 text-sm">
        {FAQ.map((item) => (
          <div key={item.q}>
            <dt className="font-medium">{item.q}</dt>
            <dd className="mt-1 space-y-2 text-muted-foreground">{item.a}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
