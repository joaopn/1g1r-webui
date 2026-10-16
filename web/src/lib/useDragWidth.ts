import { type KeyboardEvent, type PointerEvent, useRef } from "react";

/** Root font size in px, which is what a rem is (jsdom reports none: browsers default to 16). */
export function remInPixels(fallback: number): number {
  const parsed = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export function clampRem(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * Pointer and keyboard handlers for a vertical splitter that sets a width in rem: drag with
 * pointer capture (the width follows the pointer outside the handle), arrows step it
 * (Shift multiplies the step), Home/End jump to the bounds, double-click resets.
 */
export function useDragWidth({
  width,
  min,
  max,
  step,
  shiftMultiplier,
  defaultPx,
  onChange,
  onReset,
}: {
  width: number;
  min: number;
  max: number;
  step: number;
  shiftMultiplier: number;
  /** Fallback rem size in px when the document reports none. */
  defaultPx: number;
  onChange: (rem: number) => void;
  onReset: () => void;
}) {
  const drag = useRef<{ id: number; x: number; start: number; px: number } | null>(null);
  const set = (rem: number) => onChange(clampRem(rem, min, max));
  return {
    onPointerDown(event: PointerEvent<HTMLElement>) {
      if (event.button !== 0) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      drag.current = {
        id: event.pointerId,
        x: event.clientX,
        start: width,
        px: remInPixels(defaultPx),
      };
    },
    onPointerMove(event: PointerEvent<HTMLElement>) {
      const current = drag.current;
      if (!current || current.id !== event.pointerId) return;
      set(current.start + (event.clientX - current.x) / current.px);
    },
    onPointerUp(event: PointerEvent<HTMLElement>) {
      drag.current = null;
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    },
    onPointerCancel() {
      drag.current = null;
    },
    onDoubleClick(event: { stopPropagation: () => void }) {
      event.stopPropagation();
      onReset();
    },
    onClick(event: { stopPropagation: () => void }) {
      event.stopPropagation();
    },
    onKeyDown(event: KeyboardEvent<HTMLElement>) {
      const delta = event.shiftKey ? step * shiftMultiplier : step;
      const next =
        event.key === "ArrowLeft"
          ? width - delta
          : event.key === "ArrowRight"
            ? width + delta
            : event.key === "Home"
              ? min
              : event.key === "End"
                ? max
                : null;
      if (next === null) return;
      event.preventDefault();
      set(next);
    },
  };
}
