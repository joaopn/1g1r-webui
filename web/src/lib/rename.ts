import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api, json } from "@/lib/api";
import { invalidateFolder } from "@/lib/queries";

/** Saves a set's naming template (the Rename tab's proposals follow it), from Romset
 * management or the tab itself. */
export function useSaveRenameTemplate() {
  return useMutation({
    mutationFn: ({ label, template }: { label: string; template: string }) =>
      api(`/folders/${label}/rename-template`, json("PUT", { template })),
    onSuccess: (_, { label }) => {
      toast.success("Naming template saved");
      return invalidateFolder(label);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
}
