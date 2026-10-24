import { KeyRound } from "lucide-react";
import { KeyRow } from "@/components/conversion/ConsoleKeys";
import { formatCount } from "@/lib/format";
import { useConsoleKeys } from "@/lib/queries";

/** prod.keys from your own Switch: reads update versions an NSP has no cnmt.xml for, and the
 * version shown to players. Kept in the app's data folder, shared by every Switch set. */
export function SwitchKeys({ label }: { label: string }) {
  const status = useConsoleKeys().data;
  if (!status) return null;
  const generations = status.prod_keys;
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-3">
      <h2 className="flex items-center gap-2 font-semibold">
        <KeyRound className="size-4" aria-hidden="true" />
        Console keys
      </h2>
      <p className="mt-1 text-muted-foreground text-sm">
        With keys dumped from your own Switch (Lockpick_RCM), versions are read from inside each
        file. They are kept in the app's data folder and never sent anywhere. Scan again after
        adding them.
      </p>
      <ul className="mt-2">
        <KeyRow
          kind="prod_keys"
          title="prod.keys"
          help="prod.keys: reads update versions and the version shown to players."
          present={generations !== null}
          detail={
            generations === null
              ? "not added"
              : `${formatCount(generations)} key ${generations === 1 ? "generation" : "generations"}`
          }
          label={label}
          accept=".keys,.txt"
        />
      </ul>
    </section>
  );
}
