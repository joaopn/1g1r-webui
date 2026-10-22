import { useMutation } from "@tanstack/react-query";
import { Archive, Play, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ConvertDialog } from "@/components/apply/ConvertDialog";
import { RunPanel } from "@/components/apply/RunPanel";
import { useSetAside } from "@/components/apply/useSetAside";
import { ConsoleKeys } from "@/components/conversion/ConsoleKeys";
import { ConversionTable } from "@/components/conversion/ConversionTable";
import { ScanPanel } from "@/components/ScanPanel";
import { StatCard } from "@/components/StatCard";
import { UnsupportedFiles } from "@/components/UnsupportedFiles";
import { Button } from "@/components/ui/button";
import { ApiError, api, json } from "@/lib/api";
import { formatCount, formatFiles } from "@/lib/format";
import { invalidateFolder, useConversion, useFolder, useMeta } from "@/lib/queries";
import { FolderHeader } from "@/pages/FolderHeader";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

export function FolderConversionPage() {
  const { label = "" } = useParams();
  const meta = useMeta();
  const folder = useFolder(label, meta.data?.ui.poll_interval_ms ?? false);
  const conversion = useConversion(label);
  const setAside = useSetAside(label, meta.data);
  // The files under review: null is the whole folder.
  const [converting, setConverting] = useState<{ relPaths: string[] | null } | null>(null);
  const options = useMutation({
    mutationFn: (deleteOriginals: boolean) =>
      api(`/folders/${label}/conversion`, json("PUT", { delete_originals: deleteOriginals })),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => toast.error(errorText(err)),
  });

  if (folder.error) return <p className="text-status-bad">{errorText(folder.error)}</p>;
  if (!meta.data || !folder.data) return <p className="text-muted-foreground">Loading…</p>;
  const f = folder.data;
  const target = meta.data.targets[f.target];
  const platformName = meta.data.platforms[f.platform]?.name ?? f.platform;
  const counts = conversion.data?.counts;
  const toConvert = counts?.to_convert ?? 0;
  const scanning = f.scan?.status === "running";
  const cannotConvert = conversion.data?.cannot_convert ?? [];

  return (
    <div className="space-y-6">
      <FolderHeader folder={f} meta={meta.data} section="conversion" />

      <ScanPanel label={label} kind="check" scan={f.scan} title="Check files">
        <span className="font-medium">Target</span> {target?.label}{" "}
        <span className="text-muted-foreground">
          · every other file is converted to it, or discarded · set for every {platformName} folder
          in{" "}
          <Link to="/settings/conversion-targets" className="underline underline-offset-2">
            Settings → Conversion targets
          </Link>
        </span>
      </ScanPanel>

      <UnsupportedFiles
        files={f.unsupported}
        platform={f.platform}
        meta={meta.data}
        busy={scanning}
        onMove={setAside.move}
      />

      {meta.data.platforms[f.platform]?.decrypts ? <ConsoleKeys label={label} /> : null}

      {counts && counts.all > 0 ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard value={formatCount(counts.all)} label="ROM files" />
          <StatCard
            value={formatCount(counts.to_convert)}
            label="to convert"
            attention={counts.to_convert > 0}
          />
          <StatCard
            value={formatCount(counts.flagged)}
            label="flagged"
            attention={counts.flagged > 0}
          />
          <StatCard value={formatCount(counts.done)} label="already fine" />
        </div>
      ) : null}

      <section className="space-y-2 rounded-lg border border-border bg-card px-4 py-3 text-sm">
        <label className="flex items-start gap-2">
          <input
            type="checkbox"
            className="mt-0.5 size-4 accent-primary"
            checked={f.delete_originals}
            disabled={options.isPending}
            onChange={(event) => options.mutate(event.target.checked)}
          />
          <span>
            Delete the originals instead of moving them to{" "}
            <code className="text-xs">
              {f.discarded_to}
              {"originals/"}
            </code>
          </span>
        </label>
        {f.delete_originals ? (
          <p className="flex items-center gap-2 text-status-bad">
            <TriangleAlert className="size-4" aria-hidden="true" />
            Converting can then not be undone; converting will ask you to type the folder label.
          </p>
        ) : (
          <p className="text-muted-foreground">
            Every conversion is lossless and checked before the original is moved (each row's
            tooltip on "Becomes" says how), so it can be undone.
          </p>
        )}
      </section>

      <RunPanel label={label} meta={meta.data} onMove={setAside.move} />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="mr-auto font-semibold text-lg">Files</h2>
        {cannotConvert.length > 0 ? (
          <Button
            variant="outline"
            disabled={scanning}
            onClick={() => setAside.move(cannotConvert)}
            title="Review, then move every file that cannot be converted (flagged, or failed in the last conversion) to discarded/; each can be restored. Matching waits until none is left."
          >
            <Archive className="size-4" aria-hidden="true" />
            Move what can't be converted to discarded/ ({formatFiles(cannotConvert.length)})
          </Button>
        ) : null}
        <Button
          variant={f.delete_originals ? "destructive" : "default"}
          disabled={toConvert === 0 || scanning}
          onClick={() => setConverting({ relPaths: null })}
          title={toConvert === 0 ? "Nothing to convert" : "Review every conversion, then apply"}
        >
          <Play className="size-4" aria-hidden="true" />
          Convert{toConvert > 0 ? ` (${formatFiles(toConvert)})` : ""}
        </Button>
      </div>

      {conversion.data ? (
        f.scan ? (
          <ConversionTable
            rows={conversion.data.rows}
            meta={meta.data}
            busy={scanning}
            onConvert={(row) => setConverting({ relPaths: [row.rel_path] })}
            onMove={(row) => setAside.move([row.rel_path])}
          />
        ) : (
          <p className="text-muted-foreground">Scan the folder to see what it would convert.</p>
        )
      ) : (
        <p className="text-muted-foreground">Loading files…</p>
      )}

      {converting ? (
        <ConvertDialog
          label={label}
          relPaths={converting.relPaths}
          title={
            converting.relPaths?.length === 1
              ? `Convert ${converting.relPaths[0]}`
              : `Convert files in ${label}`
          }
          meta={meta.data}
          open
          onOpenChange={(open) => {
            if (!open) setConverting(null);
          }}
        />
      ) : null}
      {setAside.dialog}
    </div>
  );
}
