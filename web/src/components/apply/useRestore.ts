import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api, json } from "@/lib/api";
import { invalidateFolder } from "@/lib/queries";

export type RestoreScope = { operation_ids: number[] } | { group_key: string };

/** Move discarded files back. Refusals name each file (something changed outside the app). */
export function useRestore(label: string) {
  return useMutation({
    mutationFn: (scope: RestoreScope) => api(`/folders/${label}/restore`, json("POST", scope)),
    onSuccess: () => invalidateFolder(label),
    onError: (err) => {
      if (err instanceof ApiError && err.problems.length > 0)
        toast.error(err.message, {
          description: err.problems.map((p) => p.problem).join("\n"),
        });
      else toast.error(err instanceof ApiError ? err.message : String(err));
    },
  });
}
