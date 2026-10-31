import { FolderTree, Undo2 } from "lucide-react";
import { useState } from "react";
import { GuardedDialog } from "@/components/apply/GuardedDialog";
import { Box } from "@/components/Box";
import { Button } from "@/components/ui/button";
import { formatCount, formatFiles } from "@/lib/format";
import { useOrganize } from "@/lib/queries";
import type { Meta } from "@/lib/types";

/** Optional game folders of a title-ID set: each game's files in a folder named after it,
 * updates in update/ and DLC in dlc/ (RomM's layout for games of several files). Never part
 * of the set being done; every move can be reverted. */
export function GameFolders({ label, meta }: { label: string; meta: Meta }) {
  const organize = useOrganize(label, true);
  const [acting, setActing] = useState<"organize" | "revert" | null>(null);
  const counts = organize.data?.counts;
  const proposed = counts?.proposed ?? 0;
  const moved = counts?.moved ?? 0;
  const skipped = organize.data?.rows.filter((r) => r.status === "skipped") ?? [];
  const sub = organize.data?.subfolders;

  return (
    <>
      <Box
        title="Game folders (optional)"
        actions={
          <>
            <Button variant="outline" disabled={moved === 0} onClick={() => setActing("revert")}>
              <Undo2 className="size-4" aria-hidden="true" />
              Revert{moved > 0 ? ` (${formatFiles(moved)})` : ""}
            </Button>
            <Button
              variant="outline"
              disabled={proposed === 0}
              onClick={() => setActing("organize")}
            >
              <FolderTree className="size-4" aria-hidden="true" />
              Move{proposed > 0 ? ` (${formatFiles(proposed)})` : ""}
            </Button>
          </>
        }
      >
        <p className="text-muted-foreground">
          Each game in its own folder
          {sub?.update ? (
            <>
              , updates in <code className="text-xs">{sub.update}/</code>
            </>
          ) : null}
          {sub?.dlc ? (
            <>
              , DLC in <code className="text-xs">{sub.dlc}/</code>
            </>
          ) : null}{" "}
          (RomM's layout). File names stay. Not needed for the set to be done.
        </p>
        {counts ? (
          <p className="text-muted-foreground" data-testid="game-folders-counts">
            {formatCount(proposed)} to move · {formatCount(counts.in_place)} in place ·{" "}
            {formatCount(counts.skipped)} skipped
          </p>
        ) : null}
        {skipped.length > 0 ? (
          <details>
            <summary className="cursor-pointer text-muted-foreground">Skipped files</summary>
            <ul className="mt-1 space-y-0.5">
              {skipped.map((r) => (
                <li key={r.rel_path} className="flex min-w-0 gap-2">
                  <span className="truncate">{r.rel_path}</span>
                  <span className="ml-auto shrink-0 text-muted-foreground">{r.reason}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </Box>
      {acting ? (
        <GuardedDialog
          label={label}
          path={acting === "organize" ? "organize" : "organize/revert"}
          body={{}}
          title={
            acting === "organize"
              ? `Move the files of ${label} to game folders`
              : `Give the files of ${label} back their folders`
          }
          description={
            acting === "organize"
              ? "Each file moves to its game's folder and keeps its name. Each move can be reverted."
              : "Each file goes back to the folder it was in, with the name it has now."
          }
          action={(n) => `${acting === "organize" ? "Move" : "Revert"} ${formatFiles(n)}`}
          meta={meta}
          renames
          paths
          open
          onOpenChange={(open) => (open ? null : setActing(null))}
        />
      ) : null}
    </>
  );
}
