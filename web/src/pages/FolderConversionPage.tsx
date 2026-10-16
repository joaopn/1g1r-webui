import { useMutation } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ConversionTable } from "@/components/conversion/ConversionTable";
import { ScanPanel } from "@/components/ScanPanel";
import { StatCard } from "@/components/StatCard";
import { ApiError, api, json } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { invalidateFolder, useConversion, useFolder, useMeta } from "@/lib/queries";
import { FolderHeader } from "@/pages/FolderHeader";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

export function FolderConversionPage() {
  const { label = "" } = useParams();
  const meta = useMeta();
  const folder = useFolder(label, meta.data?.ui.poll_interval_ms ?? false);
  const conversion = useConversion(label);
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

  return (
    <div className="space-y-6">
      <FolderHeader folder={f} meta={meta.data} section="Conversion" />

      <ScanPanel label={label} scan={f.scan}>
        <span className="font-medium">Target</span> {target?.label}{" "}
        <span className="text-muted-foreground">
          · accepts {target?.accepts.join(", ")} as they are · set for every {platformName} folder
          in{" "}
          <Link to="/settings/platforms" className="underline underline-offset-2">
            Settings → Platforms &amp; files
          </Link>
        </span>
      </ScanPanel>

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
          <StatCard value={formatCount(counts.done + counts.accepted)} label="already fine" />
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
            Converting can then not be undone; applying will ask you to confirm.
          </p>
        ) : (
          <p className="text-muted-foreground">
            Every conversion is lossless and checked (CRC32 and size) before the original is moved,
            so it can be undone.
          </p>
        )}
      </section>

      {conversion.data ? (
        f.scan ? (
          <ConversionTable rows={conversion.data.rows} meta={meta.data} />
        ) : (
          <p className="text-muted-foreground">Scan the folder to see what it would convert.</p>
        )
      ) : (
        <p className="text-muted-foreground">Loading files…</p>
      )}
    </div>
  );
}
