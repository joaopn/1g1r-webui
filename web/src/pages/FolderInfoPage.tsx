import { useMutation } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { keys, queryClient, useFolder, useMeta } from "@/lib/queries";
import { FolderHeader } from "@/pages/FolderHeader";

/** Discarded: the folder's facts until that part is built. */
export function FolderInfoPage({ section }: { section: "Discarded" }) {
  const { label = "" } = useParams();
  const meta = useMeta();
  const folder = useFolder(label, false);
  const navigate = useNavigate();
  const remove = useMutation({
    mutationFn: () => api(`/folders/${label}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.folders });
      toast.success(`Removed ${label} from the app; its files are untouched`);
      navigate("/");
    },
  });
  if (!meta.data || !folder.data) return <p className="text-muted-foreground">Loading…</p>;
  const f = folder.data;
  const target = meta.data.targets[f.target];
  return (
    <div className="space-y-6">
      <FolderHeader folder={f} meta={meta.data} section={section} />
      <dl className="grid max-w-3xl grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
        <dt className="text-muted-foreground">Target format</dt>
        <dd>
          {target?.label}{" "}
          <span className="text-muted-foreground">
            — set for every {meta.data.platforms[f.platform]?.name} folder in Settings → Platforms
            &amp; files
          </span>
        </dd>
        <dt className="text-muted-foreground">Discarded files go to</dt>
        <dd>
          <code className="text-xs">{f.discarded_to}</code>
          {!f.on_main_mount ? (
            <span className="text-status-warn">
              {" "}
              (another disk: moves will be copy, verify, then remove)
            </span>
          ) : null}
        </dd>
      </dl>
      <div className="max-w-3xl rounded-lg border border-border bg-card p-6 text-muted-foreground text-sm">
        {section} for this folder arrives in a later build. Nothing in this folder is changed.
      </div>
      <Button variant="ghost" className="text-muted-foreground" onClick={() => remove.mutate()}>
        Remove from the app (files are not touched)
      </Button>
    </div>
  );
}
