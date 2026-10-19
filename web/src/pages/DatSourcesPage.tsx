import { useMutation } from "@tanstack/react-query";
import { ArrowDown, ArrowUp } from "lucide-react";
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
    what: "Hasheous: an online checksum database.",
    pros: ["Identifies files no DAT here lists, by checksum"],
    cons: [
      "Sends checksums (never files or names) over the internet",
      "Skips archives with several ROM files",
    ],
  },
  screenscraper: {
    what: "ScreenScraper: an online game database.",
    pros: ["Large database; its names also feed the suggestions"],
    cons: [
      "Needs developer and user credentials (Settings → Online lookups)",
      "Rate-limited; sends checksums; skips archives with several ROM files",
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
    </Page>
  );
}
