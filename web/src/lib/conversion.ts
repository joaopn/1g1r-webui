import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api } from "@/lib/api";
import { invalidateFolder } from "@/lib/queries";

/** Stops the folder's running conversion: no file starts, the ones under way are cut off and
 * what they wrote is deleted; files already converted stay converted. */
export function useStopConversion(label: string) {
  return useMutation({
    mutationFn: () => api(`/folders/${label}/convert/stop`, { method: "POST" }),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
}
