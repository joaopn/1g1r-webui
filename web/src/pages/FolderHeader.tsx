import { PlatformIcon } from "@/components/PlatformIcon";
import type { FolderInfo, Meta } from "@/lib/types";

export function FolderHeader({
  folder,
  meta,
  section,
}: {
  folder: FolderInfo;
  meta: Meta;
  section: string;
}) {
  const platform = meta.platforms[folder.platform];
  return (
    <header className="space-y-1">
      <div className="flex items-center gap-2">
        <PlatformIcon platform={platform} />
        <h1 className="font-semibold text-2xl tracking-tight">
          {platform?.name ?? folder.platform}
        </h1>
        <span className="text-lg text-muted-foreground">· {folder.label}</span>
      </div>
      <p className="text-muted-foreground text-sm">
        {section} ·{" "}
        <code className="text-xs">
          {folder.location ?? `mount ${folder.mount} is not available`}
        </code>
      </p>
    </header>
  );
}
