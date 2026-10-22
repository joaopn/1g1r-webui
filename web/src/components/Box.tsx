import type { ReactNode } from "react";

/** A titled panel of a folder page: its name and buttons on top, what it says below.
 * `background` is drawn behind both (a running job's progress), clipped to the panel's
 * corners in a layer of its own: the panel itself does not clip, so a popover opened from
 * its buttons can reach past its bottom edge. */
export function Box({
  title,
  actions,
  background,
  children,
}: {
  title: string;
  actions?: ReactNode;
  background?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section aria-label={title} className="relative rounded-lg border border-border bg-card">
      {background ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 overflow-hidden rounded-[inherit]"
        >
          {background}
        </div>
      ) : null}
      <div className="relative flex flex-wrap items-center justify-between gap-2 border-border border-b px-4 py-2.5">
        <h2 className="font-semibold text-lg">{title}</h2>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children ? <div className="relative space-y-1 px-4 py-3 text-sm">{children}</div> : null}
    </section>
  );
}
