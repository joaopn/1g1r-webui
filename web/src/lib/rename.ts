import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api, json } from "@/lib/api";
import { invalidateFolder, keys, queryClient } from "@/lib/queries";
import type { RenameMode } from "@/lib/types";

/** Saves a set's naming template (the Rename tab's proposals follow it), from Romset
 * management or the tab itself. */
export function useSaveRenameTemplate() {
  return useMutation({
    mutationFn: ({ label, template }: { label: string; template: string }) =>
      api(`/folders/${label}/rename-template`, json("PUT", { template })),
    onSuccess: (_, { label }) => {
      toast.success("Naming template saved");
      queryClient.invalidateQueries({ queryKey: keys.settings });
      return invalidateFolder(label);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
}

/** Switches renaming for every set (each set's own template is dropped). */
export function useSaveRenameMode() {
  return useMutation({
    mutationFn: (mode: RenameMode) => api("/settings/rename-mode", json("PUT", { mode })),
    onSuccess: () => {
      toast.success("Renaming saved");
      // Every set's template and proposals follow it.
      return queryClient.invalidateQueries();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
}
