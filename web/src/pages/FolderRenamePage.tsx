import { FilePen, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { GuardedDialog } from "@/components/apply/GuardedDialog";
import { RunPanel } from "@/components/apply/RunPanel";
import { Box } from "@/components/Box";
import { RenameTable } from "@/components/rename/RenameTable";
import { StatCard } from "@/components/StatCard";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { formatCount, formatFiles } from "@/lib/format";
import { useFolder, useFolderCard, useMeta, useRenames } from "@/lib/queries";
import { useSaveRenameTemplate } from "@/lib/rename";
import { FolderHeader } from "@/pages/FolderHeader";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

/** What a dialog acts on: every file proposed (or renamed), or one. */
type Acting = { kind: "rename" | "revert"; relPaths: string[] | null };

/** Rename: new file names from the set's naming template (chosen in Romset management), for
 * the tools that read the library after us. Each rename can be reverted: the file gets the
 * name it had before its first rename. */
export function FolderRenamePage() {
  const { label = "" } = useParams();
  const card = useFolderCard(label);
  const meta = useMeta();
  const folder = useFolder(label, false);
  const renames = useRenames(label);
  const [acting, setActing] = useState<Acting | null>(null);
  const saveTemplate = useSaveRenameTemplate();

  if (folder.error) return <p className="text-status-bad">{errorText(folder.error)}</p>;
  if (!meta.data || !folder.data) return <p className="text-muted-foreground">Loading…</p>;
  const f = folder.data;
  const data = renames.data;
  const template = meta.data.rename_templates[f.rename_template];
  const keeps = f.rename_template === "keep";
  const proposed = data?.counts.proposed ?? 0;
  const renamed = data?.counts.renamed ?? 0;
  const waiting = data?.waiting ?? 0;
  const one = (relPaths: string[] | null) => (relPaths?.length === 1 ? relPaths : null);

  return (
    <div className="space-y-6">
      <FolderHeader folder={f} meta={meta.data} section="rename" card={card} />
      {data && data.rows.length > 0 ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatCard value={formatCount(proposed)} label="to rename" />
          <StatCard value={formatCount(data.counts.named)} label="named" />
          <StatCard value={formatCount(data.counts.skipped)} label="skipped" />
          <StatCard value={formatCount(renamed)} label="renamed, can be reverted" />
        </div>
      ) : null}
      <Box
        title="Rename files"
        actions={
          <>
            <Button
              variant="outline"
              disabled={renamed === 0}
              onClick={() => setActing({ kind: "revert", relPaths: null })}
            >
              <Undo2 className="size-4" aria-hidden="true" />
              Revert{renamed > 0 ? ` (${formatFiles(renamed)})` : ""}
            </Button>
            <Button
              disabled={proposed === 0 || waiting > 0}
              onClick={() => setActing({ kind: "rename", relPaths: null })}
            >
              <FilePen className="size-4" aria-hidden="true" />
              Rename{proposed > 0 ? ` (${formatFiles(proposed)})` : ""}
            </Button>
          </>
        }
      >
        <p className="flex flex-wrap items-center gap-2" data-testid="rename-template">
          <span className="text-muted-foreground">File names:</span>
          {f.rename_templates.length > 1 ? (
            <select
              aria-label="Naming template"
              className="h-8 rounded-md border border-input bg-background px-2 text-sm"
              value={f.rename_template}
              disabled={saveTemplate.isPending}
              onChange={(event) => saveTemplate.mutate({ label, template: event.target.value })}
            >
              {f.rename_templates.map((t) => (
                <option key={t} value={t} title={meta.data?.rename_templates[t]?.description}>
                  {meta.data?.rename_templates[t]?.label ?? t}
                </option>
              ))}
            </select>
          ) : (
            <span className="font-medium">{template?.label ?? f.rename_template}</span>
          )}
        </p>
        {f.rename_templates.length > 1 ? (
          <p className="text-muted-foreground">
            {keeps
              ? "This set keeps its file names. "
              : `${template?.description ?? ""} Reverting gives a file back its original name. `}
            <Link
              to="/settings/romsets"
              className="text-primary underline-offset-2 hover:underline"
            >
              Every template is explained in Romset management
            </Link>
            .
          </p>
        ) : (
          <p className="text-muted-foreground">
            This platform's files keep their names: emulators load them by these names.
          </p>
        )}
        {waiting > 0 ? (
          <p className="text-status-warn" data-testid="rename-waiting">
            Convert or discard first: {formatFiles(waiting)} (Conversion tab).
          </p>
        ) : null}
      </Box>
      <RunPanel label={label} meta={meta.data} />
      {renames.error ? (
        <p className="text-status-bad">{errorText(renames.error)}</p>
      ) : !data ? (
        <p className="text-muted-foreground">Loading files…</p>
      ) : data.rows.length === 0 ? (
        <p className="text-muted-foreground">No ROM file in this set. Check files to look again.</p>
      ) : (
        <RenameTable
          rows={data.rows}
          meta={meta.data}
          busy={!!card?.running}
          blocked={waiting > 0}
          onRename={(relPath) => setActing({ kind: "rename", relPaths: [relPath] })}
          onRevert={(relPath) => setActing({ kind: "revert", relPaths: [relPath] })}
        />
      )}
      {acting ? (
        <GuardedDialog
          label={label}
          path={acting.kind === "rename" ? "rename" : "rename/revert"}
          body={acting.relPaths ? { rel_paths: acting.relPaths } : {}}
          title={
            acting.kind === "rename"
              ? `Rename ${one(acting.relPaths)?.[0] ?? `files of ${label}`}`
              : `Give ${one(acting.relPaths)?.[0] ?? `the files of ${label}`} back their original names`
          }
          description={
            acting.kind === "rename"
              ? "Each file gets its new name in its folder. Nothing else changes, and each can be reverted."
              : "Each file gets its original name back: the one it had before its first rename."
          }
          note="igir reads renamed files again at the next scan (the size above)."
          action={(n) => `${acting.kind === "rename" ? "Rename" : "Revert"} ${formatFiles(n)}`}
          meta={meta.data}
          renames
          open
          onOpenChange={(open) => (open ? null : setActing(null))}
        />
      ) : null}
    </div>
  );
}
