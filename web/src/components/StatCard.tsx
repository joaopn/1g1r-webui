import { cn } from "@/lib/utils";

export function StatCard({
  value,
  label,
  attention = false,
}: {
  value: string;
  label: string;
  attention?: boolean;
}) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <div className={cn("font-semibold text-2xl tabular-nums", attention && "text-status-warn")}>
        {value}
      </div>
      <div className="text-muted-foreground text-sm">{label}</div>
    </div>
  );
}
