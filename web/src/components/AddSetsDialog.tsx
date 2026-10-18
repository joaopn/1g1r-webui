import { useMutation, useQuery } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { FolderBrowser } from "@/components/FolderBrowser";
import { PlatformCombobox } from "@/components/PlatformCombobox";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError, api, json } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { platformsByName } from "@/lib/platforms";
import { keys, queryClient, useMeta } from "@/lib/queries";
import type { FolderInfo, SetCandidate, SetCandidates } from "@/lib/types";

/** What the user makes of one subfolder: add it or not, as which platform, under which label. */
type Choice = { add: boolean; platform: string; label: string };

const choiceOf = (row: SetCandidate): Choice => ({
  add: row.problem === null && row.platform !== null,
  platform: row.platform ?? "",
  label: row.label,
});

/**
 * Add sets from a folder of platform folders (roms/nes, roms/snes...): each subfolder is
 * offered with the platform its name matches; the user fixes wrong matches, unticks what
 * should not be a set, and adds the rest at once (all of them, or none).
 */
export function AddSetsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const meta = useMeta();
  const [mount, setMount] = useState("roms");
  const [path, setPath] = useState("");
  // The folder whose subfolders are listed: chosen with "List subfolders".
  const [listed, setListed] = useState<{ mount: string; path: string } | null>(null);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setPath("");
    setListed(null);
    setError(null);
  }, [open]);

  const candidates = useQuery({
    queryKey: ["set-candidates", listed?.mount, listed?.path],
    queryFn: () => api<SetCandidates>(`/set-candidates?${new URLSearchParams(listed ?? {})}`),
    enabled: open && listed !== null,
  });
  const rows = candidates.data?.rows ?? [];
  // A fresh listing starts from its own matches.
  useEffect(() => {
    setChoices(Object.fromEntries((candidates.data?.rows ?? []).map((r) => [r.path, choiceOf(r)])));
    setProblems({});
  }, [candidates.data]);

  const chosen = rows.filter((r) => r.problem === null && choices[r.path]?.add);
  const add = useMutation({
    mutationFn: () =>
      api<FolderInfo[]>(
        "/sets",
        json("POST", {
          mount: listed?.mount,
          sets: chosen.map((r) => ({
            path: r.path,
            platform: choices[r.path].platform,
            label: choices[r.path].label,
          })),
        }),
      ),
    onSuccess: async (added) => {
      await queryClient.invalidateQueries({ queryKey: keys.folders });
      toast.success(`Added ${formatCount(added.length)} ${added.length === 1 ? "set" : "sets"}`);
      onOpenChange(false);
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : String(err));
      if (err instanceof ApiError)
        setProblems(Object.fromEntries(err.problems.map((p) => [p.rel_path, p.problem])));
    },
  });

  const platforms = platformsByName(meta.data?.platforms ?? {});
  const update = (rowPath: string, change: Partial<Choice>) =>
    setChoices((old) => ({ ...old, [rowPath]: { ...old[rowPath], ...change } }));
  const ready = chosen.length > 0 && chosen.every((r) => choices[r.path].platform);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Add sets from a folder</DialogTitle>
          <DialogDescription>
            For a folder that already holds one folder per platform (roms/nes, roms/snes…). Its
            subfolders are matched to platforms by name; check the matches, fix the wrong ones,
            untick what should not be a set, and add them. A folder can be in one set only.
          </DialogDescription>
        </DialogHeader>

        {listed === null ? (
          <div className="space-y-4">
            <FolderBrowser
              mount={mount}
              path={path}
              onMount={setMount}
              onPath={setPath}
              enabled={open}
            />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="button" onClick={() => setListed({ mount, path })}>
                List subfolders
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm">
              Subfolders of <code className="text-xs">{candidates.data?.location ?? "…"}</code>
            </p>
            {error ? (
              <p role="alert" className="flex items-center gap-2 text-sm text-status-bad">
                <TriangleAlert className="size-4" aria-hidden="true" /> {error}
              </p>
            ) : null}
            {candidates.error ? (
              <p role="alert" className="text-sm text-status-bad">
                {String((candidates.error as Error).message)}
              </p>
            ) : null}
            {candidates.data && rows.length === 0 ? (
              <p className="text-muted-foreground text-sm">This folder has no subfolders.</p>
            ) : null}
            {rows.length > 0 ? (
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-left text-muted-foreground text-xs uppercase">
                    <tr>
                      <th className="w-10 px-3 py-2">Add</th>
                      <th className="px-3 py-2">Folder</th>
                      <th className="w-64 px-3 py-2">Platform</th>
                      <th className="w-40 px-3 py-2">Label</th>
                      <th className="px-3 py-2">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => {
                      const choice = choices[row.path] ?? choiceOf(row);
                      const blocked = row.problem !== null;
                      const note = problems[row.path] ?? row.problem ?? row.note;
                      const bad = problems[row.path] !== undefined || blocked;
                      return (
                        <tr key={row.path} className="border-border border-t align-top">
                          <td className="px-3 py-2">
                            <input
                              type="checkbox"
                              aria-label={`Add ${row.name}`}
                              checked={!blocked && choice.add}
                              disabled={blocked}
                              onChange={(event) => update(row.path, { add: event.target.checked })}
                            />
                          </td>
                          <td className="px-3 py-2">
                            <span className="font-medium">{row.name}</span>
                            {row.items !== null ? (
                              <span className="block text-muted-foreground text-xs">
                                {formatCount(row.items)} {row.items === 1 ? "item" : "items"}
                              </span>
                            ) : null}
                          </td>
                          <td className="px-3 py-2">
                            {blocked ? null : (
                              <PlatformCombobox
                                id={`platform-${row.path}`}
                                platforms={platforms}
                                value={choice.platform}
                                onChange={(platform) => update(row.path, { platform, add: true })}
                                iconWidthRem={meta.data?.ui.platform_icon_width_rem}
                              />
                            )}
                          </td>
                          <td className="px-3 py-2">
                            {blocked ? null : (
                              <Input
                                aria-label={`Label for ${row.name}`}
                                value={choice.label}
                                onChange={(event) =>
                                  update(row.path, { label: event.target.value })
                                }
                              />
                            )}
                          </td>
                          <td
                            className={
                              bad
                                ? "px-3 py-2 text-status-bad"
                                : choice.platform && choice.platform === row.platform
                                  ? "px-3 py-2 text-muted-foreground"
                                  : "px-3 py-2 text-status-warn"
                            }
                          >
                            {choice.platform && choice.platform !== row.platform && !bad
                              ? "chosen by you"
                              : note}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setListed(null)}>
                Back
              </Button>
              <Button type="button" disabled={!ready || add.isPending} onClick={() => add.mutate()}>
                Add {formatCount(chosen.length)} {chosen.length === 1 ? "set" : "sets"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
