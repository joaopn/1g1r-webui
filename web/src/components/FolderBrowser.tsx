import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Folder } from "lucide-react";
import { api } from "@/lib/api";
import type { Browse } from "@/lib/types";

const FIELD =
  "h-9 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** Pick a mount and a folder in it by clicking through its subfolders. */
export function FolderBrowser({
  mount,
  path,
  onMount,
  onPath,
  enabled,
}: {
  mount: string;
  path: string;
  onMount: (mount: string) => void;
  onPath: (path: string) => void;
  enabled: boolean;
}) {
  const mounts = useQuery({
    queryKey: ["mounts"],
    queryFn: () => api<{ id: string; root: string }[]>("/mounts"),
    enabled,
  });
  const browse = useQuery({
    queryKey: ["browse", mount, path],
    queryFn: () => api<Browse>(`/browse?${new URLSearchParams({ mount, path })}`),
    enabled,
  });
  const crumbs = path ? path.split("/") : [];
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <label htmlFor="mount" className="font-medium text-sm">
          Mount
        </label>
        <select
          id="mount"
          className={FIELD}
          value={mount}
          onChange={(event) => {
            onMount(event.target.value);
            onPath("");
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
        <p className="font-medium text-sm">Folder</p>
        <div className="rounded-md border border-border">
          <div className="flex flex-wrap items-center gap-1 border-border border-b px-3 py-1.5 text-sm">
            <button type="button" className="hover:underline" onClick={() => onPath("")}>
              {mount}
            </button>
            {crumbs.map((part, index) => (
              <span key={crumbs.slice(0, index + 1).join("/")} className="flex items-center gap-1">
                <ChevronRight className="size-3 text-muted-foreground" aria-hidden="true" />
                <button
                  type="button"
                  className="hover:underline"
                  onClick={() => onPath(crumbs.slice(0, index + 1).join("/"))}
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
                  onClick={() => onPath(path ? `${path}/${child}` : child)}
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
          <p className="border-border border-t px-3 py-1.5 text-sm">
            Selected: <code className="text-xs">{browse.data?.location ?? "…"}</code>
          </p>
        </div>
      </div>
    </div>
  );
}

export function useBrowse(mount: string, path: string, enabled: boolean) {
  return useQuery({
    queryKey: ["browse", mount, path],
    queryFn: () => api<Browse>(`/browse?${new URLSearchParams({ mount, path })}`),
    enabled,
  });
}
