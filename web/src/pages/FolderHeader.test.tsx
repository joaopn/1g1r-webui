import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { queryClient } from "@/lib/queries";
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
  rename_template: "keep",
  rename_templates: ["keep", "dat", "clean"],
};

test("the set's pages are tabs, the current one marked", () => {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <FolderHeader folder={FOLDER} meta={META} section="matching" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const tabs = screen.getByRole("navigation", { name: "Set pages" });
  const links = Array.from(tabs.querySelectorAll("a"));
  expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
    ["Conversion", "/folders/nes/conversion"],
    ["Matching & 1G1R", "/folders/nes/matching"],
    ["Rename", "/folders/nes/rename"],
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

test("Check files sits next to the set's name and checks the folder", async () => {
  const posted: string[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") posted.push(url);
    return new Response(JSON.stringify({}), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <FolderHeader folder={FOLDER} meta={META} section="rename" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Check files of nes" }));
  expect(posted).toEqual(["/api/folders/nes/check"]);
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
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <FolderHeader folder={FOLDER} meta={META} section="matching" card={c} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const tabs = screen.getByRole("navigation", { name: "Set pages" });
    const done = Array.from(tabs.querySelectorAll("a"))
      .filter((a) => a.querySelector('[aria-label="nothing to do"]'))
      .map((a) => a.textContent);
    unmount();
    return done;
  };
  expect(checked(card(0, 0, null))).toEqual(["Conversion", "Matching & 1G1R", "Rename"]);
  // Files still to match: Matching is not done.
  expect(checked(card(0, 2, null))).toEqual(["Conversion", "Rename"]);
  // A scan due: Matching and Rename are not done.
  expect(checked(card(0, 0, "identify"))).toEqual(["Conversion"]);
  // Files to rename: Rename is not done.
  const renaming = { template: "dat", files: 3, proposed: 2, named: 1, skipped: 0, renamed: 0 };
  expect(checked({ ...card(0, 0, null), rename: renaming } as FolderCard)).toEqual([
    "Conversion",
    "Matching & 1G1R",
  ]);
  // Files to convert: Rename has nothing to do meanwhile (those files wait); no check yet:
  // nothing is done.
  expect(checked(card(2, 2, null))).toEqual(["Rename"]);
  expect(checked(card(0, 0, "check"))).toEqual([]);
  // A set without ROM files has nothing done yet (Discarded never has a check).
  expect(checked({ ...card(0, 0, null), summary: { roms: 0 } } as FolderCard)).toEqual([]);
});

test("a Switch set has an Updates & DLC tab, checked when nothing is to discard", () => {
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
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <FolderHeader
            folder={{ ...FOLDER, title_ids: true }}
            meta={META}
            section="updates"
            card={c}
          />
        </MemoryRouter>
      </QueryClientProvider>,
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
    ["Rename", true],
    ["Discarded", false],
    ["Ignored", false],
  ]);
  expect(tabs(card(0))[2]).toEqual(["Updates & DLC", true]);
  // A version still unknown (no prod.keys yet) is no work left; a scan due is.
  expect(tabs(card(0, 1))[2]).toEqual(["Updates & DLC", true]);
  expect(tabs({ ...card(0), needs: "identify" } as FolderCard)[2]).toEqual([
    "Updates & DLC",
    false,
  ]);
});

test("other sets have no Updates tab", () => {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <FolderHeader folder={FOLDER} meta={META} section="matching" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.queryByRole("link", { name: "Updates & DLC" })).toBeNull();
});
