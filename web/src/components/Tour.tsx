import { type Driver, driver } from "driver.js";
import "driver.js/dist/driver.css";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useFolders } from "@/lib/queries";
import { isBoolean, readJson, writeJson } from "@/lib/storage";
import type { FolderCard } from "@/lib/types";

/** Set once the tour is skipped or every step is done; it never comes back in this browser. */
export const TOUR_KEY = "g1r.tour.v1";

export type TourKind = "add" | "dats" | "scan";

/**
 * The step still open, first one first: no set yet, a set whose platform has no DAT, a set
 * never scanned. "done" when sets exist and none is left; null while the sets load or a run
 * is still going.
 */
export function tourStep(folders: FolderCard[] | undefined): TourKind | "done" | null {
  if (!folders) return null;
  const visible = folders.filter((f) => !f.hidden);
  if (visible.length === 0) return "add";
  if (visible.some((f) => f.needs_dat)) return "dats";
  if (visible.some((f) => f.needs_scan)) return "scan";
  // A running check or conversion reports nothing due yet: a Scan may still follow it.
  if (visible.some((f) => f.scan?.status === "running" || f.converting)) return null;
  return "done";
}

type Mark = { key: string; element: HTMLElement; title: string; description: string };

const TEXT = {
  add: {
    title: "Add romsets",
    description: "Start here: pick a platform folder, or a folder of platform folders.",
  },
  dats: {
    title: "Platform DATs",
    description: "Get a DAT for each platform. Most download with one click.",
  },
  check: {
    title: "Check files",
    description: "Lists the set and finds what needs converting. Nothing is hashed.",
  },
  identify: { title: "Scan", description: "Identifies the files against the DATs." },
};

/** On screen: a closed group, a collapsed sidebar or a closed menu sheet has no boxes. */
function shown(element: Element | null): element is HTMLElement {
  return element instanceof HTMLElement && element.getClientRects().length > 0;
}

function firstShown(selector: string): HTMLElement | undefined {
  return Array.from(document.querySelectorAll(selector)).find(shown);
}

function findMark(kind: TourKind): Mark | undefined {
  if (kind === "scan") {
    const element = firstShown('[data-tour="scan"]');
    const step = element?.dataset.tourStep === "check" ? TEXT.check : TEXT.identify;
    return (
      element && {
        key: `scan:${element.dataset.tourSet}:${element.dataset.tourStep}`,
        element,
        ...step,
      }
    );
  }
  const element = firstShown(
    kind === "add" ? '[data-tour="add-romsets"]' : '[data-tour="platform-dats"]',
  );
  return element && { key: kind, element, ...TEXT[kind] };
}

/**
 * Coach marks on Home for a first run: the control to click is lit, the rest dimmed. The mark
 * follows the state (no Next button); clicking the control or the dimmed page hides that mark.
 * `reveal` brings a sidebar target on screen (a group opened, the sidebar or menu shown).
 */
export function Tour({ reveal }: { reveal: (group?: string) => void }) {
  const home = useLocation().pathname === "/";
  const folders = useFolders();
  const [finished, setFinished] = useState(() => readJson(TOUR_KEY, false, isBoolean));
  const [paused, setPaused] = useState<string | null>(null);
  const tour = useRef<Driver | null>(null);
  const active = useRef<Mark | null>(null);
  const revealed = useRef<string | null>(null);
  const kind = finished ? "done" : tourStep(folders.data);

  const hide = () => {
    tour.current?.destroy();
    active.current = null;
  };

  useEffect(() => {
    if (kind === "done") {
      if (!finished) {
        writeJson(TOUR_KEY, true);
        setFinished(true);
      }
      hide();
      return;
    }
    if (!home || kind === null) {
      hide();
      return;
    }
    // After the render: Home's cards and an opened group are in the page by then.
    const frame = requestAnimationFrame(() => {
      const mark = findMark(kind);
      if (!mark) {
        hide();
        // A sidebar target is offscreen: show it once; closed again by hand, it stays closed.
        if (kind !== "scan" && revealed.current !== kind) {
          revealed.current = kind;
          reveal(kind === "dats" ? "settings" : undefined);
        }
        return;
      }
      if (mark.key === paused) return hide();
      if (active.current?.key === mark.key && active.current.element === mark.element) return;
      const pause = () => {
        setPaused(mark.key);
        hide();
      };
      tour.current ??= driver();
      tour.current.setConfig({
        popoverClass: "g1r-tour",
        nextBtnText: "Skip tour",
        onNextClick: () => {
          writeJson(TOUR_KEY, true);
          setFinished(true);
          hide();
        },
        // Escape and a click on the dimmed page: hidden until the step changes.
        onDestroyStarted: pause,
      });
      active.current = mark;
      tour.current.highlight({
        element: mark.element,
        // A lone highlight drops the buttons unless the step names them.
        popover: { title: mark.title, description: mark.description, showButtons: ["next"] },
      });
      // The control does its real job; the mark steps aside for the dialog or page it opens.
      mark.element.addEventListener("click", pause, { once: true });
    });
    return () => cancelAnimationFrame(frame);
  });

  // The menu sheet slides in: look for the target again, or place the mark again, once it
  // stands still.
  const [, setSettled] = useState(false);
  useEffect(() => {
    const refresh = () => {
      if (tour.current?.isActive()) tour.current.refresh();
      else setSettled((settled) => !settled);
    };
    document.addEventListener("animationend", refresh);
    return () => {
      document.removeEventListener("animationend", refresh);
      tour.current?.destroy();
    };
  }, []);

  return null;
}
