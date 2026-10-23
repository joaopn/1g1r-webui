import { CircleCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { PlatformIcon } from "@/components/PlatformIcon";
import { folderState, SECTIONS, type SectionId, sectionDone, sectionPath } from "@/lib/sections";
import type { FolderCard, FolderInfo, Meta } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The set's name and location, then its pages as tabs across the full width; a page with
 * nothing left to do (from the set's Home `card`) has a green check. */
export function FolderHeader({
  folder,
  meta,
  section,
  card,
}: {
  folder: FolderInfo;
  meta: Meta;
  section: SectionId;
  card?: FolderCard;
}) {
  const platform = meta.platforms[folder.platform];
  return (
    <header className="space-y-4">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <PlatformIcon platform={platform} state={card ? folderState(card) : undefined} />
          <h1 className="font-semibold text-2xl tracking-tight">
            {platform?.name ?? folder.platform}
          </h1>
          <span className="text-lg text-muted-foreground">· {folder.label}</span>
        </div>
        <p className="text-muted-foreground text-sm">
          <code className="text-xs">
            {folder.location ?? `mount ${folder.mount} is not available`}
          </code>
        </p>
      </div>
      <nav aria-label="Set pages" className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1">
        {SECTIONS.map(({ id, label, icon: Icon }) => (
          <Link
            key={id}
            to={sectionPath(folder.label, id)}
            aria-current={id === section ? "page" : undefined}
            className={cn(
              "flex min-w-0 items-center justify-center gap-2 rounded-md px-2 py-2.5 font-medium text-sm transition-colors sm:px-3 sm:text-base",
              id === section
                ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
            )}
          >
            <Icon className="hidden size-5 shrink-0 sm:block" aria-hidden="true" />
            <span className="truncate">{label}</span>
            {card && sectionDone(card, id) ? (
              <CircleCheck
                className="size-4 shrink-0 text-status-good"
                aria-label="nothing to do"
                role="img"
              />
            ) : null}
          </Link>
        ))}
      </nav>
    </header>
  );
}
