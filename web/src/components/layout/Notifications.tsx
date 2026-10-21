import { Bell, CircleAlert, CircleCheck, LoaderCircle, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { ApiError, api } from "@/lib/api";
import { formatCount, formatWhen } from "@/lib/format";
import { keys, queryClient, useFolders, useNotifications } from "@/lib/queries";
import { isStringArray, readJson, writeJson } from "@/lib/storage";
import type { Notification } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The finished items this browser has seen in the panel; the others count as unread. */
const SEEN_KEY = "g1r.notifications.seen.v1";

/** Which folder page an item opens. */
const PAGES: Record<Notification["kind"], string> = {
  scan: "matching",
  conversion: "conversion",
  "1g1r": "matching",
  unmatched: "matching",
  empty: "discarded",
  restore: "discarded",
};

function progressText(item: Notification): string {
  if (item.kind === "scan") {
    if (!item.stage) return "Waiting to start…";
    if (item.done === null || item.total === null) return `${item.stage}…`;
    return `${item.stage}: ${formatCount(item.done)} / ${formatCount(item.total)} files`;
  }
  return `${formatCount(item.done ?? 0)} / ${formatCount(item.total ?? 0)} files`;
}

function StatusIcon({ status }: { status: Notification["status"] }) {
  if (status === "running")
    return (
      <LoaderCircle
        className="size-4 shrink-0 animate-spin text-status-info motion-reduce:animate-none"
        aria-label="Running"
      />
    );
  if (status === "failed")
    return <CircleAlert className="size-4 shrink-0 text-status-bad" aria-label="Failed" />;
  return <CircleCheck className="size-4 shrink-0 text-status-good" aria-label="Done" />;
}

async function dismiss(id?: string) {
  try {
    await api(id ? `/notifications/${id}` : "/notifications", { method: "DELETE" });
  } catch (err) {
    toast.error(err instanceof ApiError ? err.message : String(err));
  }
  await queryClient.invalidateQueries({ queryKey: keys.notifications });
}

function Item({
  item,
  unread,
  known,
  onOpen,
}: {
  item: Notification;
  unread: boolean;
  known: boolean;
  onOpen: () => void;
}) {
  const running = item.status === "running";
  const fraction =
    running && item.done !== null && item.total ? Math.min(item.done / item.total, 1) : null;
  return (
    <li
      data-testid={`notification-${item.id}`}
      className={cn(
        "group relative flex gap-3 rounded-md border border-border p-3 text-sm",
        unread && "bg-accent/50",
      )}
    >
      <StatusIcon status={item.status} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-baseline gap-2">
          <span className="font-medium">{item.title}</span>
          {known ? (
            <Link
              to={`/folders/${item.folder_label}/${PAGES[item.kind]}`}
              onClick={onOpen}
              className="truncate text-muted-foreground text-xs underline-offset-2 hover:underline"
            >
              {item.folder_label}
            </Link>
          ) : (
            <span className="truncate text-muted-foreground text-xs">{item.folder_label}</span>
          )}
          {unread ? (
            <span className="ml-auto size-2 shrink-0 rounded-full bg-primary" title="New" />
          ) : null}
        </div>
        {running ? (
          <>
            <span className="text-muted-foreground text-xs">{progressText(item)}</span>
            {fraction !== null ? (
              <div className="h-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full origin-left bg-status-info"
                  style={{ transform: `scaleX(${fraction})` }}
                />
              </div>
            ) : null}
          </>
        ) : item.message ? (
          <span
            className={cn(
              "line-clamp-3 break-words text-xs",
              item.status === "failed" ? "text-status-bad" : "text-muted-foreground",
            )}
            title={item.message}
          >
            {item.message}
          </span>
        ) : null}
        <span className="text-muted-foreground text-xs">
          {formatWhen(item.finished_at ?? item.started_at)}
        </span>
      </div>
      {running ? null : (
        <button
          type="button"
          aria-label={`Dismiss ${item.title} ${item.folder_label}`}
          onClick={() => dismiss(item.id)}
          className="absolute top-2 right-2 rounded p-0.5 text-muted-foreground opacity-0 hover:bg-accent hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100"
        >
          <X className="size-3.5" />
        </button>
      )}
    </li>
  );
}

/** The bell at the top right: the latest scans and runs of every set in a side panel. */
export function Notifications() {
  const feed = useNotifications();
  const folders = useFolders();
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(() => new Set(readJson(SEEN_KEY, [], isStringArray)));
  const items = feed.data ?? [];
  const finished = items.filter((i) => i.status !== "running");
  const unread = finished.filter((i) => !seen.has(i.id));
  const running = items.length - finished.length;
  const known = new Set((folders.data ?? []).map((f) => f.label));

  // Everything finished counts as seen once the panel closes; while it is open the new
  // ones stay marked so you can tell them apart.
  const markSeen = () => {
    const ids = finished.map((i) => i.id);
    writeJson(SEEN_KEY, ids);
    setSeen(new Set(ids));
  };
  const onOpenChange = (next: boolean) => {
    if (!next) markSeen();
    setOpen(next);
  };

  const label = [
    "Notifications",
    running ? `${running} running` : "",
    unread.length ? `${unread.length} new` : "",
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={label}
          title={label}
          data-testid="notifications"
          className="relative"
        >
          {running ? (
            <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />
          ) : (
            <Bell className="size-4" />
          )}
          {unread.length ? (
            <span
              data-testid="notifications-unread"
              className={cn(
                "-top-0.5 -right-0.5 absolute flex h-4 min-w-4 items-center justify-center rounded-full px-1 font-medium text-[0.625rem] text-white leading-none",
                unread.some((i) => i.status === "failed") ? "bg-status-bad" : "bg-primary",
              )}
            >
              {unread.length}
            </span>
          ) : null}
        </Button>
      </SheetTrigger>
      <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
        <SheetHeader className="border-border border-b pr-12">
          <SheetTitle>Notifications</SheetTitle>
          <SheetDescription>
            Scans, conversions, applies and restores of every set.
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {items.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground text-sm">No notifications.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {items.map((item) => (
                <Item
                  key={item.id}
                  item={item}
                  unread={item.status !== "running" && !seen.has(item.id)}
                  known={known.has(item.folder_label)}
                  onOpen={() => onOpenChange(false)}
                />
              ))}
            </ul>
          )}
        </div>
        <div className="flex justify-end gap-2 border-border border-t p-4">
          <Button
            variant="outline"
            size="sm"
            disabled={finished.length === 0}
            onClick={() => dismiss()}
            data-testid="notifications-clear"
          >
            Clear
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
