import { Gamepad, Gamepad2, Joystick, Keyboard } from "lucide-react";
import type { FolderState } from "@/lib/sections";
import type { Platform } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * A platform's icon: its short name ("GB", "NES", "MD") in a chip, with a glyph for the
 * kind of device. Text rather than brand logos: every platform gets a distinct, readable
 * mark, and no console maker's trademark is reproduced. In a list, pass `widthRem` so every
 * badge has the same width and the names beside them line up. For a set, `state` colours it
 * (and names the state for screen readers); a bare platform stays neutral.
 */
// Literal class names, so Tailwind generates them.
const STATES: Record<FolderState, { tone: string; words: string }> = {
  bad: { tone: "border-status-bad/40 bg-status-bad/10 text-status-bad", words: "error" },
  warn: { tone: "border-status-warn/40 bg-status-warn/10 text-status-warn", words: "warning" },
  done: {
    tone: "border-status-good/40 bg-status-good/10 text-status-good",
    words: "nothing to do",
  },
  work: { tone: "border-status-info/40 bg-status-info/10 text-status-info", words: "work to do" },
};

export function PlatformIcon({
  platform,
  state,
  widthRem,
  className,
}: {
  platform?: Platform;
  state?: FolderState;
  widthRem?: number;
  className?: string;
}) {
  const GLYPHS = { handheld: Gamepad, arcade: Joystick, computer: Keyboard, console: Gamepad2 };
  const Glyph = GLYPHS[platform?.kind ?? "console"];
  return (
    <span
      {...(state
        ? { role: "img", "aria-label": `${platform?.short ?? "?"}: ${STATES[state].words}` }
        : { "aria-hidden": true })}
      data-state={state}
      style={widthRem === undefined ? undefined : { width: `${widthRem}rem` }}
      className={cn(
        "inline-flex h-5 shrink-0 items-center justify-center gap-0.5 rounded-sm border px-1 font-semibold text-[10px] leading-none tracking-tight",
        state ? STATES[state].tone : "border-border bg-muted text-muted-foreground",
        className,
      )}
    >
      <Glyph className="size-3" />
      {platform?.short ?? "?"}
    </span>
  );
}
