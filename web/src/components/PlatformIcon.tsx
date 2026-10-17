import { Gamepad, Gamepad2, Joystick } from "lucide-react";
import type { Platform } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * A platform's icon: its short name ("GB", "NES", "MD") in a chip, with a glyph for the
 * kind of device. Text rather than brand logos: every platform gets a distinct, readable
 * mark, and no console maker's trademark is reproduced. In a list, pass `widthRem` so every
 * badge has the same width and the names beside them line up.
 */
export function PlatformIcon({
  platform,
  widthRem,
  className,
}: {
  platform?: Platform;
  widthRem?: number;
  className?: string;
}) {
  const Glyph =
    platform?.kind === "handheld" ? Gamepad : platform?.kind === "arcade" ? Joystick : Gamepad2;
  return (
    <span
      aria-hidden="true"
      style={widthRem === undefined ? undefined : { width: `${widthRem}rem` }}
      className={cn(
        "inline-flex h-5 shrink-0 items-center justify-center gap-0.5 rounded-sm border px-1 font-semibold text-[10px] leading-none tracking-tight",
        platform?.kind === "handheld"
          ? "border-status-info/40 bg-status-info/10 text-status-info"
          : platform?.kind === "arcade"
            ? "border-status-good/40 bg-status-good/10 text-status-good"
            : "border-primary/40 bg-primary/10 text-primary",
        className,
      )}
    >
      <Glyph className="size-3" />
      {platform?.short ?? "?"}
    </span>
  );
}
