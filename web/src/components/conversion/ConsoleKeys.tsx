import { useMutation } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useRef } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ApiError, api, upload } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { invalidateFolder, keys, queryClient, useConsoleKeys } from "@/lib/queries";
import type { KeyStatus } from "@/lib/types";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

type Kind = "boot9" | "seeddb" | "prod_keys";

/** One key file: whether it is there, and add / replace / remove buttons. */
export function KeyRow({
  kind,
  title,
  help,
  present,
  detail,
  label,
  accept = ".bin",
}: {
  kind: Kind;
  title: string;
  help: string;
  present: boolean;
  detail: string;
  label: string;
  /** The file picker's types. */
  accept?: string;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const done = (status: KeyStatus) => {
    queryClient.setQueryData(keys.consoleKeys, status);
    // What can be decrypted changes with the keys.
    invalidateFolder(label);
  };
  const add = useMutation({
    mutationFn: (file: File) => api<KeyStatus>(`/keys/${kind}`, upload(file)),
    onSuccess: (status) => {
      toast.success(`${title} added`);
      done(status);
    },
    onError: (err) => toast.error(errorText(err)),
  });
  const remove = useMutation({
    mutationFn: () => api<KeyStatus>(`/keys/${kind}`, { method: "DELETE" }),
    onSuccess: (status) => {
      toast.success(`${title} removed`);
      done(status);
    },
    onError: (err) => toast.error(errorText(err)),
  });
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-2">
      <div className="min-w-0">
        <p className="font-medium">
          {title}{" "}
          <span className={present ? "text-status-good" : "text-muted-foreground"}>· {detail}</span>
        </p>
        <p className="text-muted-foreground text-sm">{help}</p>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={add.isPending}
          onClick={() => fileInput.current?.click()}
        >
          {present ? "Replace" : "Add"}
        </Button>
        {present ? (
          <Button
            variant="outline"
            size="sm"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            Remove
          </Button>
        ) : null}
        <input
          ref={fileInput}
          type="file"
          accept={accept}
          className="hidden"
          aria-label={`${title} file`}
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) add.mutate(file);
            event.target.value = "";
          }}
        />
      </div>
    </li>
  );
}

/** The console keys 3DS decryption needs, added here and kept in the app's data folder. */
export function ConsoleKeys({ label }: { label: string }) {
  const status = useConsoleKeys();
  const data = status.data;
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-3">
      <h2 className="flex items-center gap-2 font-semibold">
        <KeyRound className="size-4" aria-hidden="true" />
        Console keys
      </h2>
      <p className="mt-1 text-muted-foreground text-sm">
        Encrypted card images are decrypted with keys dumped from your own 3DS (GodMode9). They are
        kept in the app's data folder, shared by every 3DS folder, and never sent anywhere.
      </p>
      {data ? (
        <ul className="mt-2 divide-y divide-border">
          <KeyRow
            kind="boot9"
            title="boot9"
            help="boot9.bin or boot9_prot.bin: needed to decrypt anything."
            present={data.boot9}
            detail={data.boot9 ? "added" : "missing"}
            label={label}
          />
          <KeyRow
            kind="seeddb"
            title="seeddb"
            help="seeddb.bin: only for titles encrypted with a seed (digital releases)."
            present={data.seeddb !== null}
            detail={
              data.seeddb === null
                ? "not added"
                : `${formatCount(data.seeddb)} ${data.seeddb === 1 ? "seed" : "seeds"}`
            }
            label={label}
          />
        </ul>
      ) : null}
    </section>
  );
}
