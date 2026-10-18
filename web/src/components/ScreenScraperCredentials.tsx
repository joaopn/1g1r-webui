import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, api, json } from "@/lib/api";
import { keys, queryClient } from "@/lib/queries";
import type { CredentialField, CredentialSources } from "@/lib/types";

const FIELDS: { id: CredentialField; label: string; secret: boolean }[] = [
  { id: "devid", label: "Developer ID", secret: false },
  { id: "devpassword", label: "Developer password", secret: true },
  { id: "user", label: "Username", secret: false },
  { id: "password", label: "Password", secret: true },
];

/** ScreenScraper's credentials: entered here, kept on the server, never shown again. */
export function ScreenScraperCredentials({
  sources,
  environment,
}: {
  sources: CredentialSources;
  environment: Record<CredentialField, string>;
}) {
  const [values, setValues] = useState<Partial<Record<CredentialField, string>>>({});
  const done = (message: string) => {
    toast.success(message);
    setValues({});
    queryClient.invalidateQueries({ queryKey: keys.settings });
  };
  const onError = (err: unknown) =>
    toast.error(err instanceof ApiError ? err.message : String(err));
  const save = useMutation({
    mutationFn: (body: Partial<Record<CredentialField, string>>) =>
      api("/settings/screenscraper-credentials", json("PUT", body)),
    onSuccess: () => done("ScreenScraper credentials saved"),
    onError,
  });
  const remove = useMutation({
    mutationFn: () => api("/settings/screenscraper-credentials", { method: "DELETE" }),
    onSuccess: () => done("ScreenScraper credentials removed"),
    onError,
  });
  const entered = Object.fromEntries(Object.entries(values).filter(([, v]) => v));
  const stored = FIELDS.some((f) => sources[f.id] === "app");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate(entered);
  };
  return (
    <form onSubmit={submit} className="space-y-3" data-testid="screenscraper-credentials">
      <p className="text-muted-foreground">
        The developer pair is required; your account raises the daily quota. Saved values are never
        shown again: type a new one to replace it.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map((f) => {
          const source = sources[f.id];
          return (
            <div key={f.id} className="space-y-1">
              <label htmlFor={`screenscraper-${f.id}`} className="block font-medium">
                {f.label}
              </label>
              <Input
                id={`screenscraper-${f.id}`}
                type={f.secret ? "password" : "text"}
                autoComplete="off"
                value={values[f.id] ?? ""}
                disabled={source === "environment"}
                placeholder={
                  source === "environment"
                    ? `set by ${environment[f.id]}`
                    : source === "app"
                      ? "saved"
                      : "not set"
                }
                onChange={(event) => setValues((v) => ({ ...v, [f.id]: event.target.value }))}
              />
            </div>
          );
        })}
      </div>
      <div className="flex gap-2">
        <Button type="submit" disabled={Object.keys(entered).length === 0 || save.isPending}>
          Save credentials
        </Button>
        {stored ? (
          <Button
            type="button"
            variant="outline"
            disabled={remove.isPending}
            onClick={() => remove.mutate()}
          >
            Remove saved credentials
          </Button>
        ) : null}
      </div>
    </form>
  );
}
