import { useMutation } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { FolderBrowser, useBrowse } from "@/components/FolderBrowser";
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
import { Label } from "@/components/ui/label";
import { ApiError, api, json } from "@/lib/api";
import { platformsByName } from "@/lib/platforms";
import { keys, queryClient, useMeta } from "@/lib/queries";
import type { FolderInfo } from "@/lib/types";

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

  const browse = useBrowse(mount, path, open);

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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add single folder</DialogTitle>
          <DialogDescription>
            A set is one folder of games of <strong>one platform only</strong>, with its label.
            Every set is handled on its own, even when two have the same platform, and a folder can
            be in one set only.
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

          <div className="space-y-2">
            <Label htmlFor="platform">Platform</Label>
            <PlatformCombobox
              id="platform"
              platforms={platforms}
              value={platform}
              onChange={setPlatform}
              iconWidthRem={meta.data?.ui.platform_icon_width_rem}
            />
            <p className="text-muted-foreground text-xs">
              Only supported platforms are listed. The target format is set per platform in Settings
              → Conversion targets.
            </p>
          </div>

          <FolderBrowser
            mount={mount}
            path={path}
            onMount={setMount}
            onPath={setPath}
            enabled={open}
          />

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
              Add set
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
