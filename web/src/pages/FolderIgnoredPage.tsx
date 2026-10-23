import { Plus, RotateCcw, X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useParams } from "react-router-dom";
import { Box } from "@/components/Box";
import { IgnoredTable } from "@/components/ignored/IgnoredTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { useSaveIgnored } from "@/lib/ignored";
import { useFolder, useFolderCard, useMeta } from "@/lib/queries";
import { FolderHeader } from "@/pages/FolderHeader";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

/** One entry of the ignore list, with a button taking it off. */
function Entry({
  text,
  what,
  disabled,
  onRemove,
}: {
  text: string;
  what: string;
  disabled: boolean;
  onRemove: () => void;
}) {
  return (
    <li className="flex min-w-0 items-center gap-1 rounded-md border border-border bg-background py-0.5 pr-0.5 pl-2">
      <code className="truncate text-xs" title={text}>
        {text}
      </code>
      <Button
        variant="ghost"
        size="icon-xs"
        disabled={disabled}
        onClick={onRemove}
        aria-label={`Stop ignoring ${what} ${text}`}
        title="Stop ignoring"
      >
        <X aria-hidden="true" />
      </Button>
    </li>
  );
}

/** Ignored: the set's own ignore list (filename patterns and single files) and the files it
 * leaves out. Ignored files are never converted, matched, moved or counted. */
export function FolderIgnoredPage() {
  const { label = "" } = useParams();
  const card = useFolderCard(label);
  const meta = useMeta();
  const folder = useFolder(label, meta.data?.ui.poll_interval_ms ?? false);
  const save = useSaveIgnored(label);
  const [draft, setDraft] = useState("");

  if (folder.error) return <p className="text-status-bad">{errorText(folder.error)}</p>;
  if (!meta.data || !folder.data) return <p className="text-muted-foreground">Loading…</p>;
  const f = folder.data;
  const patterns = f.ignored_patterns;
  const files = f.ignored_files;
  const ignored = f.others.filter((file) => file.kind === "ignored");
  const busy = save.isPending;
  const checking = f.scan?.status === "running";

  const add = (event: FormEvent) => {
    event.preventDefault();
    const pattern = draft.trim();
    if (!pattern) return;
    if (!patterns.includes(pattern)) save.mutate({ patterns: [...patterns, pattern], files });
    setDraft("");
  };

  return (
    <div className="space-y-6">
      <FolderHeader folder={f} meta={meta.data} section="ignored" card={card} />
      <Box
        title="Ignore list"
        actions={
          !f.ignored_patterns_default ? (
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => save.mutate({ patterns: null, files })}
              title="Replace this set's patterns with the default ones"
            >
              <RotateCcw className="size-3.5" aria-hidden="true" /> Default patterns
            </Button>
          ) : null
        }
      >
        <p className="text-muted-foreground">
          Files on this list are never converted, matched, moved or counted, in this set only.
          Patterns match the file name (<code>*</code> wildcards, case-insensitive). Saving checks
          the files again.
        </p>
        <h3 className="pt-2 font-medium">
          Patterns
          {f.ignored_patterns_default ? (
            <span className="font-normal text-muted-foreground"> · default</span>
          ) : null}
        </h3>
        {patterns.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5" aria-label="Ignored patterns">
            {patterns.map((p) => (
              <Entry
                key={p}
                text={p}
                what="pattern"
                disabled={busy}
                onRemove={() => save.mutate({ patterns: patterns.filter((x) => x !== p), files })}
              />
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">None.</p>
        )}
        <form onSubmit={add} className="flex max-w-md gap-2 pt-1">
          <Input
            aria-label="New pattern"
            placeholder="*.png"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="h-8"
          />
          <Button type="submit" variant="outline" size="sm" disabled={busy || !draft.trim()}>
            <Plus className="size-3.5" aria-hidden="true" /> Add pattern
          </Button>
        </form>
        <h3 className="pt-2 font-medium">Files</h3>
        {files.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5" aria-label="Ignored files by path">
            {files.map((file) => (
              <Entry
                key={file}
                text={file}
                what="file"
                disabled={busy}
                onRemove={() => save.mutate({ patterns, files: files.filter((x) => x !== file) })}
              />
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">
            None. Files not in a supported format can be added from their warning on the Conversion
            and Matching tabs.
          </p>
        )}
      </Box>
      <section className="space-y-2">
        <h2 className="font-semibold text-lg">
          Ignored files ({formatCount(ignored.length)})
          {checking ? (
            <span className="font-normal text-muted-foreground text-sm"> · checking files…</span>
          ) : null}
        </h2>
        {ignored.length > 0 ? (
          <IgnoredTable files={ignored} meta={meta.data} />
        ) : (
          <p className="text-muted-foreground text-sm">
            The last check found no ignored file in this set.
          </p>
        )}
      </section>
    </div>
  );
}
