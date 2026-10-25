import { useMutation } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ChevronRight } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ApiError, api, json } from "@/lib/api";
import { keys, queryClient, useGlobalDatOrder, useSettingsData } from "@/lib/queries";
import type { GlobalDatOrder } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Page } from "@/pages/SettingsPages";

type Guide = { what: ReactNode; pros: string[]; cons: string[] };

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
};

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

/** Which DAT sources and lookups identify files, in which order, for every platform. */
export function DatSourcesPage() {
  const order = useGlobalDatOrder();
  const settings = useSettingsData();
  const [draft, setDraft] = useState<GlobalDatOrder["entries"]>([]);
  useEffect(() => {
    if (order.data) setDraft(order.data.entries);
  }, [order.data]);
  const save = useMutation({
    mutationFn: (reset: boolean) =>
      api<GlobalDatOrder>(
        "/dat-order",
        json("PUT", {
          order: reset ? null : draft.map((e) => e.id),
          off: draft.filter((e) => !e.on).map((e) => e.id),
        }),
      ),
    onSuccess: () => {
      toast.success("DAT order saved; scan a set to use it");
      queryClient.invalidateQueries({ queryKey: keys.datOrder });
      queryClient.invalidateQueries({ queryKey: keys.dats });
      queryClient.invalidateQueries({ queryKey: keys.folders });
      queryClient.invalidateQueries({ queryKey: ["folder"] });
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const move = (index: number, by: number) => {
    const next = [...draft];
    const [item] = next.splice(index, 1);
    next.splice(index + by, 0, item);
    setDraft(next);
  };
  const lookupsOn = settings.data?.lookups;

  return (
    <Page
      title="Which DATs to use?"
      intro={
        <>
          A DAT lists every known dump of a platform's games with its checksums. Files are
          identified top to bottom: each source tries the files the ones above it did not identify,
          and 1G1R works from the names they give. A platform uses the sources it has a DAT from (
          <Link to="/settings/dats" className="underline underline-offset-2">
            Platform DATs
          </Link>
          ); this order is for every platform without its own (DAT order on a Matching page).
        </>
      }
    >
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="border-border border-b text-left text-muted-foreground text-xs uppercase tracking-wide">
            <tr>
              <th className="px-3 py-2">Order</th>
              <th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Good</th>
              <th className="px-3 py-2">Less good</th>
              <th className="px-3 py-2">Use</th>
            </tr>
          </thead>
          <tbody>
            {draft.map((entry, index) => {
              const guide = GUIDE[entry.id];
              const lookupOff =
                entry.lookup && lookupsOn && !lookupsOn[entry.id as keyof typeof lookupsOn];
              return (
                <tr
                  key={entry.id}
                  className={cn(
                    "border-border border-b align-top last:border-b-0",
                    !entry.on && "text-muted-foreground",
                  )}
                  data-testid={`source-${entry.id}`}
                >
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1">
                      <span className="w-5 text-muted-foreground tabular-nums">{index + 1}</span>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        disabled={index === 0}
                        onClick={() => move(index, -1)}
                        aria-label={`Move ${entry.label} up`}
                      >
                        <ArrowUp aria-hidden="true" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        disabled={index === draft.length - 1}
                        onClick={() => move(index, 1)}
                        aria-label={`Move ${entry.label} down`}
                      >
                        <ArrowDown aria-hidden="true" />
                      </Button>
                    </div>
                  </td>
                  <td className="max-w-64 px-3 py-2.5">
                    <div className="font-medium">{entry.label}</div>
                    <div className="text-muted-foreground text-xs">{guide?.what}</div>
                    {lookupOff ? (
                      <Link
                        to="/settings/lookups"
                        className="text-status-warn text-xs underline underline-offset-2"
                      >
                        switched off in Online lookups
                      </Link>
                    ) : null}
                  </td>
                  <td className="px-3 py-2.5">
                    <ul className="list-disc space-y-0.5 pl-4 text-xs">
                      {guide?.pros.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ul>
                  </td>
                  <td className="px-3 py-2.5">
                    <ul className="list-disc space-y-0.5 pl-4 text-xs">
                      {guide?.cons.map((c) => (
                        <li key={c}>{c}</li>
                      ))}
                    </ul>
                  </td>
                  <td className="px-3 py-2.5">
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        className="size-3.5 accent-primary"
                        checked={entry.on}
                        onChange={() =>
                          setDraft(draft.map((e) => (e.id === entry.id ? { ...e, on: !e.on } : e)))
                        }
                        aria-label={`Use ${entry.label}`}
                      />
                      {entry.on ? "on" : "off"}
                    </label>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex justify-end gap-2">
        {order.data?.own ? (
          <Button variant="ghost" disabled={save.isPending} onClick={() => save.mutate(true)}>
            Back to the default order
          </Button>
        ) : null}
        <Button disabled={save.isPending || draft.length === 0} onClick={() => save.mutate(false)}>
          Save order
        </Button>
      </div>
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
          <strong>Matching</strong>: each file's checksums are compared with the DATs, in the order
          above. igir matches a multi-file game only when every file the DAT lists is in the
          archive. The file gets the DAT's game name; its own file name plays no part.
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
