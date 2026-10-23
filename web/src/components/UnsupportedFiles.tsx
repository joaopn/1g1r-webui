import { Archive, EyeOff, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatBytes, formatFiles } from "@/lib/format";
import { formatPattern, useIgnore } from "@/lib/ignored";
import type { FolderInfo, Meta, UnsupportedFile } from "@/lib/types";

/** The files a scan found that are not in a format the folder's platform supports: they are
 * never converted, matched or moved by the app, and the user is told so instead of seeing them
 * vanish. `onMove` (when given) reviews moving them to discarded/. Each file can go on the
 * set's ignore list, by itself or with every file of its format (not an archive format: that
 * would ignore the ROMs zipped in it too). */
export function UnsupportedFiles({
  files,
  folder,
  meta,
  onMove,
  busy = false,
}: {
  files: UnsupportedFile[];
  folder: FolderInfo;
  meta: Meta;
  onMove?: (relPaths: string[]) => void;
  busy?: boolean;
}) {
  const ignore = useIgnore(folder);
  if (files.length === 0) return null;
  const platform = folder.platform;
  const profile = meta.platforms[platform];
  const archiveSet = new Set(meta.archive_extensions.map((e) => `*.${e.toLowerCase()}`));
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
            or moved unless you move them. Ignoring a file or its format puts it on this set's
            Ignored tab.
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
          {files.map((file) => {
            const pattern = formatPattern(file.rel_path);
            const archive = pattern !== null && archiveSet.has(pattern);
            return (
              <li key={file.rel_path} className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="xs"
                  disabled={busy || ignore.busy}
                  onClick={() => ignore.file(file.rel_path)}
                  aria-label={`Ignore ${file.rel_path}`}
                  title="Add this file to the set's ignore list"
                >
                  <EyeOff aria-hidden="true" /> File
                </Button>
                {pattern ? (
                  <Button
                    variant="outline"
                    size="xs"
                    disabled={busy || ignore.busy || archive}
                    onClick={() => ignore.pattern(pattern)}
                    aria-label={`Ignore every ${pattern} file`}
                    title={
                      archive
                        ? `${pattern} also holds ROMs: ignore the file instead`
                        : `Add ${pattern} to the set's ignore list`
                    }
                  >
                    <EyeOff aria-hidden="true" /> {pattern}
                  </Button>
                ) : null}
                <span className="min-w-0 flex-1 truncate">{file.rel_path}</span>
                <span className="shrink-0 text-muted-foreground">
                  {file.reason} ·{" "}
                  {formatBytes(file.size, meta.ui.byte_unit_base, meta.ui.byte_units)}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </details>
  );
}
