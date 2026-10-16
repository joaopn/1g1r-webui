import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronRight, Folder, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, api, json } from "@/lib/api";
import { platformsByName } from "@/lib/platforms";
import { keys, queryClient, useMeta } from "@/lib/queries";
import type { Browse, FolderInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

const FIELD =
  "h-9 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function AddPlatformDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const meta = useMeta();
  const navigate = useNavigate();
  const [platform, setPlatform] = useState("");
  const [mount, setMount] = useState("roms");
  const [path, setPath] = useState("");
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setPlatform("");
    setPath("");
    setLabel("");
    setError(null);
  }, [open]);

  const mounts = useQuery({
    queryKey: ["mounts"],
    queryFn: () => api<{ id: string; root: string }[]>("/mounts"),
    enabled: open,
  });
  const browse = useQuery({
    queryKey: ["browse", mount, path],
    queryFn: () => api<Browse>(`/browse?${new URLSearchParams({ mount, path })}`),
    enabled: open,
  });

  const add = useMutation({
    mutationFn: () => api<FolderInfo>("/folders", json("POST", { platform, mount, path, label })),
    onSuccess: async (folder) => {
      await queryClient.invalidateQueries({ queryKey: keys.folders });
      toast.success(`Added ${folder.label}`);
      onOpenChange(false);
      navigate(`/folders/${folder.label}/matching`);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : String(err)),
  });

  const platforms = platformsByName(meta.data?.platforms ?? {});
  const crumbs = path ? path.split("/") : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add platform</DialogTitle>
          <DialogDescription>
            A folder must contain games of <strong>one platform only</strong>. Every folder is
            handled on its own, even when two folders have the same platform.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            setError(null);
            add.mutate();
          }}
        >
          {error ? (
            <p role="alert" className="flex items-center gap-2 text-sm text-status-bad">
              <TriangleAlert className="size-4" aria-hidden="true" /> {error}
            </p>
          ) : null}

          <fieldset className="space-y-2">
            <legend className="font-medium text-sm">Platform</legend>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3" role="radiogroup">
              {platforms.map(([id, p]) => (
                // biome-ignore lint/a11y/useSemanticElements: a styled radio card; aria-checked carries the state.
                <button
                  key={id}
                  type="button"
                  role="radio"
                  aria-checked={platform === id}
                  onClick={() => setPlatform(id)}
                  className={cn(
                    "flex items-center gap-2 rounded-md border px-2 py-1.5 text-left text-sm transition-colors",
                    platform === id
                      ? "border-primary bg-primary/10"
                      : "border-border hover:bg-accent/60",
                  )}
                >
                  <PlatformIcon platform={p} widthRem={meta.data?.ui.platform_icon_width_rem} />
                  <span className="truncate">{p.name}</span>
                </button>
              ))}
            </div>
            <p className="text-muted-foreground text-xs">
              Only supported platforms are listed. The target format is set per platform in Settings
              → Platforms &amp; files.
            </p>
          </fieldset>

          <div className="space-y-2">
            <Label htmlFor="mount">Mount</Label>
            <select
              id="mount"
              className={FIELD}
              value={mount}
              onChange={(event) => {
                setMount(event.target.value);
                setPath("");
              }}
            >
              {(mounts.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.root}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <span className="font-medium text-sm">Folder</span>
            <div className="rounded-md border border-border">
              <div className="flex flex-wrap items-center gap-1 border-border border-b px-2 py-1.5 text-sm">
                <button type="button" className="hover:underline" onClick={() => setPath("")}>
                  {mount}
                </button>
                {crumbs.map((part, index) => (
                  <span
                    key={crumbs.slice(0, index + 1).join("/")}
                    className="flex items-center gap-1"
                  >
                    <ChevronRight className="size-3 text-muted-foreground" aria-hidden="true" />
                    <button
                      type="button"
                      className="hover:underline"
                      onClick={() => setPath(crumbs.slice(0, index + 1).join("/"))}
                    >
                      {part}
                    </button>
                  </span>
                ))}
              </div>
              <ul className="max-h-56 overflow-y-auto py-1" aria-label="Subfolders">
                {(browse.data?.children ?? []).map((child) => (
                  <li key={child}>
                    <button
                      type="button"
                      onClick={() => setPath(path ? `${path}/${child}` : child)}
                      className="flex w-full items-center gap-2 px-3 py-1 text-left text-sm hover:bg-accent/60"
                    >
                      <Folder className="size-4 text-muted-foreground" aria-hidden="true" />
                      {child}
                    </button>
                  </li>
                ))}
                {browse.data && browse.data.children.length === 0 ? (
                  <li className="px-3 py-1 text-muted-foreground text-sm">No subfolders</li>
                ) : null}
              </ul>
              <p className="border-border border-t px-2 py-1.5 text-sm">
                Selected: <code className="text-xs">{browse.data?.location ?? "…"}</code>
              </p>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="label">Label</Label>
            <Input
              id="label"
              value={label}
              placeholder={browse.data?.suggested_label || "e.g. nes"}
              onChange={(event) => setLabel(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">
              Names the folder in the sidebar and its <code>discarded/&lt;label&gt;/</code>{" "}
              directory. Leave empty to use the folder name.
            </p>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!platform || add.isPending}>
              Add platform
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
