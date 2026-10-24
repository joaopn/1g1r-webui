import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { FolderCard, FolderInfo, FolderWarning } from "@/lib/types";
import { META } from "@/test/fixtures";
import { FolderHeader } from "./FolderHeader";

const FOLDER: FolderInfo = {
  label: "nes",
  platform: "nes",
  mount: "roms",
  path: "nes",
  location: "/roms/nes",
  on_main_mount: true,
  target: "/roms/nes",
  discarded_to: "/roms/discarded/nes/",
  delete_originals: false,
  hidden: false,
  ignored_patterns: [],
  ignored_patterns_default: true,
  ignored_files: [],
  title_ids: false,
};

test("the set's pages are tabs, the current one marked", () => {
  render(
    <MemoryRouter>
      <FolderHeader folder={FOLDER} meta={META} section="matching" />
    </MemoryRouter>,
  );
  const tabs = screen.getByRole("navigation", { name: "Set pages" });
  const links = Array.from(tabs.querySelectorAll("a"));
  expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
    ["Conversion", "/folders/nes/conversion"],
    ["Matching & 1G1R", "/folders/nes/matching"],
    ["Discarded", "/folders/nes/discarded"],
    ["Ignored", "/folders/nes/ignored"],
  ]);
  expect(screen.getByRole("link", { name: "Matching & 1G1R" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.getByRole("link", { name: "Conversion" })).not.toHaveAttribute("aria-current");
  expect(screen.getByText("/roms/nes")).toBeInTheDocument();
});

test("a page with nothing left to do has a green check on its tab", () => {
  // Only what the checks read.
  const card = (to_convert: number, to_process: number, needs: FolderCard["needs"]) =>
    ({
      summary: { roms: 3 },
      progress: { to_convert, to_process },
      needs,
      warnings: [] as FolderWarning[],
    }) as FolderCard;
  const checked = (c: FolderCard) => {
    const { unmount } = render(
      <MemoryRouter>
        <FolderHeader folder={FOLDER} meta={META} section="matching" card={c} />
      </MemoryRouter>,
    );
    const tabs = screen.getByRole("navigation", { name: "Set pages" });
    const done = Array.from(tabs.querySelectorAll("a"))
      .filter((a) => a.querySelector('[aria-label="nothing to do"]'))
      .map((a) => a.textContent);
    unmount();
    return done;
  };
  expect(checked(card(0, 0, null))).toEqual(["Conversion", "Matching & 1G1R"]);
  // Files still to match: only Conversion is done.
  expect(checked(card(0, 2, null))).toEqual(["Conversion"]);
  // A scan due: Matching is not done.
  expect(checked(card(0, 0, "identify"))).toEqual(["Conversion"]);
  // Files to convert, or no check yet: nothing is done.
  expect(checked(card(2, 2, null))).toEqual([]);
  expect(checked(card(0, 0, "check"))).toEqual([]);
  // A set without ROM files has nothing done yet (Discarded never has a check).
  expect(checked({ ...card(0, 0, null), summary: { roms: 0 } } as FolderCard)).toEqual([]);
});

test("a Switch set has an Updates tab, checked when no older update is proposed and every version is read", () => {
  const card = (proposed: number, unknown = 0) =>
    ({
      summary: { roms: 3 },
      progress: { to_convert: 0, to_process: 0 },
      needs: null,
      updates: { total: 2, proposed, unknown, unreadable: 0, dlc: 0 },
      warnings: [] as FolderWarning[],
    }) as FolderCard;
  const tabs = (c: FolderCard) => {
    const { unmount } = render(
      <MemoryRouter>
        <FolderHeader
          folder={{ ...FOLDER, title_ids: true }}
          meta={META}
          section="updates"
          card={c}
        />
      </MemoryRouter>,
    );
    const links = Array.from(
      screen.getByRole("navigation", { name: "Set pages" }).querySelectorAll("a"),
    );
    const found = links.map((a) => [
      a.textContent,
      a.querySelector('[aria-label="nothing to do"]') !== null,
    ]);
    unmount();
    return found;
  };
  expect(tabs(card(1))).toEqual([
    ["Conversion", true],
    ["Matching & 1G1R", true],
    ["Updates & DLC", false],
    ["Discarded", false],
    ["Ignored", false],
  ]);
  expect(tabs(card(0))[2]).toEqual(["Updates & DLC", true]);
  // A version still unknown (no prod.keys yet) is work left, and so is a scan due.
  expect(tabs(card(0, 1))[2]).toEqual(["Updates & DLC", false]);
  expect(tabs({ ...card(0), needs: "identify" } as FolderCard)[2]).toEqual([
    "Updates & DLC",
    false,
  ]);
});

test("other sets have no Updates tab", () => {
  render(
    <MemoryRouter>
      <FolderHeader folder={FOLDER} meta={META} section="matching" />
    </MemoryRouter>,
  );
  expect(screen.queryByRole("link", { name: "Updates & DLC" })).toBeNull();
});
