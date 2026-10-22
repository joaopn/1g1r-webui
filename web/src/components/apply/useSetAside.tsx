import { useState } from "react";
import { GuardedDialog } from "@/components/apply/GuardedDialog";
import { formatFiles } from "@/lib/format";
import type { Meta } from "@/lib/types";

/** Review, then move flagged or unsupported files, or files a conversion failed on, to
 * discarded/<label>/manual/ (restorable). */
export function useSetAside(label: string, meta: Meta | undefined) {
  const [relPaths, setRelPaths] = useState<string[] | null>(null);
  const dialog =
    relPaths && meta ? (
      <GuardedDialog
        label={label}
        path="set-aside"
        body={{ rel_paths: relPaths }}
        title={`Move ${relPaths.length === 1 ? relPaths[0] : formatFiles(relPaths.length)} to discarded/`}
        description={`These files move to ${meta.discarded_root}/${label}/manual/, and can be restored from the Discarded page.`}
        action={(n) => `Move ${formatFiles(n)}`}
        meta={meta}
        open
        onOpenChange={(open) => {
          if (!open) setRelPaths(null);
        }}
      />
    ) : null;
  return { move: setRelPaths, dialog };
}
