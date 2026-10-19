import type { ReactNode } from "react";

/** A titled panel of a folder page: its name and buttons on top, what it says below. */
export function Box({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section aria-label={title} className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-border border-b px-4 py-2.5">
        <h2 className="font-semibold text-lg">{title}</h2>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children ? <div className="space-y-1 px-4 py-3 text-sm">{children}</div> : null}
    </section>
  );
}
