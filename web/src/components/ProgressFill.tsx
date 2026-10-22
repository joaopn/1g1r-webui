import { cn } from "@/lib/utils";

/** A faint bar filling its (relative, overflow-hidden) container from the left: a running
 * job's progress behind the content. `fraction` null is a job of unknown length: it pulses. */
export function ProgressFill({
  fraction,
  className,
  testId,
}: {
  fraction: number | null;
  className: string;
  testId?: string;
}) {
  return (
    <div
      aria-hidden="true"
      data-testid={testId}
      className={cn(
        "pointer-events-none absolute inset-0 origin-left transition-transform duration-500",
        className,
        fraction === null && "animate-pulse",
      )}
      style={fraction === null ? undefined : { transform: `scaleX(${fraction})` }}
    />
  );
}
