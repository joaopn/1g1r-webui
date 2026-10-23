import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api, json } from "@/lib/api";
import { invalidateFolder } from "@/lib/queries";
import type { FolderInfo } from "@/lib/types";

/** A set's ignore list as saved: `patterns` null goes back to the configured default. */
export type IgnoreList = { patterns: string[] | null; files: string[] };

/** The pattern that ignores every file with this one's extension, or null without one. */
export function formatPattern(relPath: string): string | null {
  const name = relPath.split("/").pop() ?? relPath;
  const dot = name.lastIndexOf(".");
  return dot > 0 ? `*${name.slice(dot).toLowerCase()}` : null;
}

/** Saves the set's ignore list; the server then checks the files so the change shows at once. */
export function useSaveIgnored(label: string) {
  const save = useMutation({
    mutationFn: (list: IgnoreList) =>
      api<FolderInfo & { checking: boolean }>(`/folders/${label}/ignored`, json("PUT", list)),
    onSuccess: (saved) => {
      toast.success(
        saved.checking
          ? "Ignore list saved; checking files"
          : "Ignore list saved; it applies at the next check or scan",
      );
      return invalidateFolder(label);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  return save;
}

/** Adds one file or one extension pattern to the set's ignore list. */
export function useIgnore(folder: FolderInfo) {
  const save = useSaveIgnored(folder.label);
  const list = (): IgnoreList => ({
    patterns: folder.ignored_patterns,
    files: folder.ignored_files,
  });
  return {
    busy: save.isPending,
    file: (relPath: string) =>
      save.mutate({ ...list(), files: [...folder.ignored_files, relPath] }),
    pattern: (pattern: string) =>
      save.mutate({ ...list(), patterns: [...folder.ignored_patterns, pattern] }),
  };
}
