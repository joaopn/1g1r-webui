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

/** A conversion run waits for another folder's (one runs at a time): what to say, or null
 * when it is not waiting. `waitingFor` is that folder ("" when its turn is about to come). */
export function waitingText(waitingFor: string | null | undefined): string | null {
  if (waitingFor === null || waitingFor === undefined) return null;
  return waitingFor ? `Waiting for the conversion of ${waitingFor}` : "Waiting to start";
}
