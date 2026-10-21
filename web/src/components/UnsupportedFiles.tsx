import { Archive, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatBytes, formatFiles } from "@/lib/format";
import type { Meta, UnsupportedFile } from "@/lib/types";

/** The files a scan found that are not in a format the folder's platform supports: they are
 * never converted, matched or moved by the app, and the user is told so instead of seeing them
 * vanish. `onMove` (when given) reviews moving them to discarded/. */
export function UnsupportedFiles({
  files,
  platform,
  meta,
  onMove,
  busy = false,
}: {
  files: UnsupportedFile[];
  platform: string;
  meta: Meta;
  onMove?: (relPaths: string[]) => void;
  busy?: boolean;
}) {
  if (files.length === 0) return null;
  const profile = meta.platforms[platform];
  const formats = (profile?.rom_extensions ?? []).map((e) => `.${e}`).join(", ");
  const archives = meta.archive_extensions.map((e) => `.${e}`).join(" or ");
  return (
    <details className="rounded-lg border border-status-warn bg-card">
      <summary className="flex cursor-pointer items-center gap-2 px-4 py-3 font-medium text-status-warn">
        <TriangleAlert className="size-4 shrink-0" aria-hidden="true" />
        {formatFiles(files.length)} not in a supported {profile?.name ?? platform} format, left
        alone
      </summary>
      <div className="space-y-2 border-border border-t px-4 py-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <p className="min-w-56 flex-1 text-muted-foreground">
            Supported: {formats}, bare or inside {archives}. These files are not converted, matched
            or moved unless you move them.
          </p>
          {onMove ? (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => onMove(files.map((f) => f.rel_path))}
              title="Review, then move these files to discarded/ (can be restored)"
            >
              <Archive className="size-3.5" aria-hidden="true" /> Move {formatFiles(files.length)}{" "}
              to discarded/
            </Button>
          ) : null}
        </div>
        <ul className="space-y-1">
          {files.map((file) => (
            <li key={file.rel_path} className="flex justify-between gap-4">
              <span className="truncate">{file.rel_path}</span>
              <span className="shrink-0 text-muted-foreground">
                {file.reason} · {formatBytes(file.size, meta.ui.byte_unit_base, meta.ui.byte_units)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}
