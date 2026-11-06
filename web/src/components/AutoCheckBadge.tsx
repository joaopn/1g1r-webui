import { useMutation } from "@tanstack/react-query";
import { TimerReset } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api, json } from "@/lib/api";
import { keys, queryClient } from "@/lib/queries";
import { cn } from "@/lib/utils";

/**
 * The set's auto-check switch, as a badge: on, the app runs Check files on the set by itself
 * whenever its last check or scan is older than the interval in Settings → Advanced. `compact`
 * drops the word (Home's narrow cards), keeping the icon, the tooltip and the label.
 */
export function AutoCheckBadge({
  label,
  on,
  compact = false,
  className,
}: {
  label: string;
  on: boolean;
  compact?: boolean;
  className?: string;
}) {
  const save = useMutation({
    mutationFn: (auto_check: boolean) =>
      api(`/folders/${label}/auto-check`, json("PUT", { auto_check })),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.folders });
      queryClient.invalidateQueries({ queryKey: keys.folder(label) });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : String(err)),
  });
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={`Auto-check ${label}`}
      title={
        on
          ? "Auto-check on: the set is checked for new files by itself (how often: Settings → Advanced). Click to turn off."
          : "Auto-check off. Click to have the set checked for new files by itself."
      }
      disabled={save.isPending}
      onClick={() => save.mutate(!on)}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border py-0.5 font-medium text-xs transition-colors disabled:opacity-60",
        compact ? "px-1" : "px-2",
        on
          ? "border-primary bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:border-primary/50 hover:text-foreground",
        className,
      )}
    >
      <TimerReset className="size-3.5" aria-hidden="true" />
      {compact ? null : "Auto-check"}
    </button>
  );
}
