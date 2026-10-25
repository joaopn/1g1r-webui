import { useMutation } from "@tanstack/react-query";
import { ChevronRight, Eye, EyeOff, Trash2 } from "lucide-react";
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
import { formatFiles } from "@/lib/format";
import { foldersByName } from "@/lib/platforms";
import { keys, queryClient, useFolders, useMeta, useSettingsData } from "@/lib/queries";
import { useSaveRenameTemplate } from "@/lib/rename";
import { folderState } from "@/lib/sections";
import type { FolderCard } from "@/lib/types";
import { Page } from "@/pages/SettingsPages";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

/**
 * Every set, hidden ones included: its platform's target format, show or hide it, or remove it
 * from the library. The target format is per platform, so changing it on one set changes it on
 * every set of that platform.
 */
export function RomsetManagementPage() {
  const meta = useMeta();
  const folders = useFolders();
  const data = useSettingsData();
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
  const saveTarget = useMutation({
    mutationFn: (targets: Record<string, string>) =>
      api("/settings/targets", json("PUT", { targets })),
    onSuccess: () => {
      toast.success("Target format saved");
      queryClient.invalidateQueries({ queryKey: keys.settings });
      refresh();
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const saveTemplate = useSaveRenameTemplate();
  if (!meta.data || !folders.data || !data.data)
    return <p className="text-muted-foreground">Loading…</p>;
  const sets = foldersByName(folders.data, meta.data.platforms);
  const targets = data.data.targets;
  const templates = meta.data.rename_templates;
  // The templates some set here may pick, in their configured order.
  const offered = Object.keys(templates).filter((id) =>
    sets.some((set) => set.rename_templates.includes(id)),
  );

  return (
    <Page
      title="Romset management"
      intro="Each platform folder you added (a set), with its label. The target format applies to every set of that platform; the file names template is the set's own (its Rename tab). Hidden sets leave the sidebar and Home but stay added: their folder cannot be added again until removed. Removing one touches no file."
    >
      {offered.length > 0 ? (
        <details
          aria-label="File name templates"
          className="group rounded-lg border border-border bg-card px-4 py-3 text-sm"
          data-testid="templates"
        >
          <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold">
            <ChevronRight
              className="size-4 shrink-0 transition-transform group-open:rotate-90"
              aria-hidden="true"
            />
            File name templates
          </summary>
          <div className="mt-2 space-y-2">
            <p className="text-muted-foreground">
              What a set's Rename tab proposes. Only files identified by checksum, title ID or by
              you are renamed, in their folder, keeping their extension; every rename can be
              reverted to the file's first name.
            </p>
            <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-[auto_1fr]">
              {offered.map((id) => (
                <div key={id} className="contents" data-testid={`template-${id}`}>
                  <dt className="font-medium">{templates[id].label}</dt>
                  <dd className="text-muted-foreground">
                    {templates[id].description}
                    {templates[id].example ? (
                      <>
                        {" "}
                        e.g.{" "}
                        <code className="text-foreground text-xs">{templates[id].example}</code>
                      </>
                    ) : null}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </details>
      ) : null}
      {sets.length === 0 ? (
        <p className="text-muted-foreground text-sm">No sets yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="whitespace-nowrap text-left text-muted-foreground text-xs uppercase">
              <tr>
                <th className="px-3 py-2">Set</th>
                <th className="px-3 py-2">Platform</th>
                <th className="px-3 py-2">Folder</th>
                <th className="px-3 py-2">Target format</th>
                <th className="px-3 py-2">File names</th>
                <th className="px-3 py-2 text-right">Actions</th>
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
                    <td className="px-3 py-2 font-medium">
                      {set.label}
                      {set.hidden ? (
                        <span className="ml-2 font-normal text-muted-foreground text-xs">
                          hidden
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex items-center gap-2">
                        <PlatformIcon platform={platform} state={folderState(set)} />
                        {platform?.name ?? set.platform}
                      </span>
                      <span
                        className="mt-0.5 block text-muted-foreground text-xs"
                        title="ROM extensions"
                      >
                        {platform?.rom_extensions.join(", ")}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <code className="text-xs">{set.location ?? set.path}</code>
                    </td>
                    <td className="px-3 py-2">
                      {platform ? (
                        <select
                          aria-label={`Target format for ${set.label}`}
                          className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                          value={targets[set.platform]}
                          disabled={saveTarget.isPending}
                          onChange={(event) =>
                            saveTarget.mutate({ [set.platform]: event.target.value })
                          }
                        >
                          {platform.targets.map((t) => (
                            <option key={t} value={t} title={meta.data?.targets[t]?.description}>
                              {meta.data?.targets[t]?.label ?? t}
                            </option>
                          ))}
                        </select>
                      ) : null}
                    </td>
                    <td className="px-3 py-2">
                      <select
                        aria-label={`File names for ${set.label}`}
                        className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                        value={set.rename_template}
                        disabled={saveTemplate.isPending}
                        onChange={(event) =>
                          saveTemplate.mutate({ label: set.label, template: event.target.value })
                        }
                      >
                        {set.rename_templates.map((t) => (
                          <option key={t} value={t} title={templates[t]?.description}>
                            {templates[t]?.label ?? t}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-3 py-2">
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
