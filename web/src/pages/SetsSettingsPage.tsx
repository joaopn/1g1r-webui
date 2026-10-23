import { useMutation } from "@tanstack/react-query";
import { Eye, EyeOff, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { PlatformIcon } from "@/components/PlatformIcon";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiError, api, json } from "@/lib/api";
import { formatBytes, formatFiles } from "@/lib/format";
import { foldersByName } from "@/lib/platforms";
import { keys, queryClient, useFolders, useMeta } from "@/lib/queries";
import { folderState } from "@/lib/sections";
import type { FolderCard } from "@/lib/types";
import { Page } from "@/pages/SettingsPages";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

/** Every set, hidden ones included: show or hide each, or remove it from the library. */
export function SetsSettingsPage() {
  const meta = useMeta();
  const folders = useFolders();
  const [removing, setRemoving] = useState<FolderCard | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: keys.folders });
  const hide = useMutation({
    mutationFn: ({ label, hidden }: { label: string; hidden: boolean }) =>
      api(`/folders/${label}/hidden`, json("PUT", { hidden })),
    onSuccess: refresh,
    onError: (err) => toast.error(errorText(err)),
  });
  const remove = useMutation({
    mutationFn: (label: string) => api(`/folders/${label}`, { method: "DELETE" }),
    onSuccess: (_, label) => {
      toast.success(`Removed the set ${label}`);
      setRemoving(null);
      refresh();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  if (!meta.data || !folders.data) return <p className="text-muted-foreground">Loading…</p>;
  const ui = meta.data.ui;
  const sets = foldersByName(folders.data, meta.data.platforms);

  return (
    <Page
      title="Folders"
      intro="Each platform folder you added (a set), with its label. Hidden ones leave the sidebar and Home but stay added: their folder cannot be added again until removed. Removing one touches no file."
    >
      {sets.length === 0 ? (
        <p className="text-muted-foreground text-sm">No sets yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="text-left text-muted-foreground text-xs uppercase">
              <tr>
                <th className="px-4 py-2">Set</th>
                <th className="px-4 py-2">Platform</th>
                <th className="px-4 py-2">Folder</th>
                <th className="px-4 py-2">In discarded/</th>
                <th className="px-4 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sets.map((set) => {
                const platform = meta.data.platforms[set.platform];
                return (
                  <tr
                    key={set.label}
                    className={
                      set.hidden ? "border-border border-t opacity-60" : "border-border border-t"
                    }
                  >
                    <td className="px-4 py-2 font-medium">
                      {set.label}
                      {set.hidden ? (
                        <span className="ml-2 font-normal text-muted-foreground text-xs">
                          hidden
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-2">
                      <span className="flex items-center gap-2">
                        <PlatformIcon platform={platform} state={folderState(set)} />
                        {platform?.name ?? set.platform}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <code className="text-xs">{set.location ?? set.path}</code>
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {set.discarded.files > 0
                        ? `${formatFiles(set.discarded.files)}, ${formatBytes(set.discarded.bytes, ui.byte_unit_base, ui.byte_units)}`
                        : "nothing"}
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          className="gap-1.5"
                          disabled={hide.isPending}
                          onClick={() => hide.mutate({ label: set.label, hidden: !set.hidden })}
                        >
                          {set.hidden ? (
                            <Eye className="size-3.5" aria-hidden="true" />
                          ) : (
                            <EyeOff className="size-3.5" aria-hidden="true" />
                          )}
                          {set.hidden ? "Show" : "Hide"}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="gap-1.5"
                          onClick={() => setRemoving(set)}
                        >
                          <Trash2 className="size-3.5" aria-hidden="true" />
                          Remove
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={removing !== null} onOpenChange={(open) => (open ? null : setRemoving(null))}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove the set {removing?.label}?</DialogTitle>
            <DialogDescription>
              The set leaves the library; no file is touched, in{" "}
              <code className="text-xs">{removing?.location ?? removing?.path}</code> or elsewhere.
              {removing && removing.discarded.files > 0 ? (
                <>
                  {" "}
                  Its {formatFiles(removing.discarded.files)} in{" "}
                  <code className="text-xs">{removing.discarded_to}</code> stay there; adding the
                  folder again under the same label shows them again.
                </>
              ) : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRemoving(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => removing && remove.mutate(removing.label)}
            >
              Remove set
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Page>
  );
}
