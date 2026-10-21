import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { queryClient } from "@/lib/queries";
import type { FolderCard, Scan } from "@/lib/types";
import { META } from "@/test/fixtures";
import { HomePage } from "./HomePage";

const SCAN: Scan = {
  id: 1,
  status: "done",
  started_at: "2026-10-18T10:00:00Z",
  finished_at: "2026-10-18T10:01:00Z",
  message: "done",
  stage: null,
  files_done: null,
  files_total: null,
};

const card = (label: string, platform: string, scan: Scan | null): FolderCard => ({
  label,
  platform,
  mount: "roms",
  path: label,
  location: `/roms/${label}`,
  on_main_mount: true,
  target: "zip",
  discarded_to: `/roms/discarded/${label}/`,
  delete_originals: false,
  hidden: false,
  scan,
  dat: null,
  summary: { counts: {}, roms: 0, bytes: 0, identified: 0, unmatched: 0, methods: {} },
  dat_download: null,
  needs_dat: false,
  needs_scan: scan === null || scan.status === "failed",
  counts: {},
  reclaim_bytes: 0,
  conversion: { to_convert: 0, flagged: 0 } as FolderCard["conversion"],
  progress: { processed: 0, to_process: 0, to_match: 0, to_convert: 0 },
  discarded: { files: 0, bytes: 0 },
  converting: null,
  warnings: [],
});

/** A set with figures: its warnings slot and scan line show, not the empty box. */
const filled = (c: FolderCard): FolderCard => ({ ...c, summary: { ...c.summary, roms: 1 } });

beforeEach(() => localStorage.clear());

function renderPage(folders: FolderCard[]) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = url.endsWith("/meta") ? META : url.endsWith("/folders") ? folders : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return calls;
}

test("a running scan fills the card by file count and its button waits", async () => {
  renderPage([
    card("nes", "nes", {
      ...SCAN,
      status: "running",
      finished_at: null,
      stage: "Reading archives",
      files_done: 25,
      files_total: 100,
    }),
  ]);
  expect(await screen.findByTestId("scan-status-nes")).toHaveTextContent(
    "Reading archives: 25 / 100 files",
  );
  expect(screen.getByTestId("scan-progress")).toHaveStyle({ transform: "scaleX(0.25)" });
  expect(screen.getByRole("button", { name: "Scan nes" })).toBeDisabled();
});

test("Simplified has no scan line: a running scan leads the warnings block", async () => {
  localStorage.setItem("g1r.home.detail.v1", JSON.stringify("simplified"));
  renderPage([
    filled(card("nes", "nes", { ...SCAN, status: "running", stage: "Reading archives" })),
  ]);
  expect(await screen.findByTestId("warnings-nes")).toContainElement(
    screen.getByTestId("scan-status-nes"),
  );
});

test("a running conversion fills the card by steps finished, with the files failed", async () => {
  renderPage([
    {
      ...card("psx", "psx", SCAN),
      converting: { done: 30, total: 40, failed: 2, stopping: false },
    },
  ]);
  expect(await screen.findByTestId("conversion-status-psx")).toHaveTextContent(
    "Converting: 75% · 2 files failed",
  );
  expect(screen.getByTestId("conversion-progress")).toHaveStyle({ transform: "scaleX(0.75)" });
  expect(screen.queryByTestId("scan-progress")).toBeNull();
  expect(screen.getByRole("button", { name: "Scan psx" })).toBeDisabled();
});

test("Stop on the card stops the set's conversion; a stopping one says so", async () => {
  const converting = { done: 1, total: 4, failed: 0, stopping: false };
  const calls = renderPage([
    { ...card("psx", "psx", SCAN), converting },
    { ...card("gb", "gb", SCAN), converting: { ...converting, stopping: true } },
    card("nes", "nes", SCAN),
  ]);
  await userEvent.click(await screen.findByRole("button", { name: "Stop the conversion of psx" }));
  expect(
    calls.some((c) => c.url.endsWith("/folders/psx/convert/stop") && c.init?.method === "POST"),
  ).toBe(true);
  expect(screen.getByRole("button", { name: "Stop the conversion of gb" })).toBeDisabled();
  expect(screen.getByTestId("conversion-status-gb")).toHaveTextContent(/^Stopping: 25%$/);
  expect(screen.queryByRole("button", { name: "Stop the conversion of nes" })).toBeNull();
});

test("Simplified: a running conversion leads the warnings block", async () => {
  localStorage.setItem("g1r.home.detail.v1", JSON.stringify("simplified"));
  renderPage([
    {
      ...filled(card("psx", "psx", SCAN)),
      converting: { done: 0, total: 4, failed: 0, stopping: false },
    },
  ]);
  expect(await screen.findByTestId("warnings-psx")).toContainElement(
    screen.getByTestId("conversion-status-psx"),
  );
  expect(screen.getByTestId("conversion-status-psx")).toHaveTextContent(/^Converting: 0%$/);
});

test("a step without a file count pulses the whole card", async () => {
  renderPage([
    card("nes", "nes", {
      ...SCAN,
      status: "running",
      stage: "Matching checksums with igir",
    }),
  ]);
  expect(await screen.findByTestId("scan-status-nes")).toHaveTextContent(
    "Matching checksums with igir…",
  );
  expect(screen.getByTestId("scan-progress")).toHaveClass("animate-pulse");
});

test("the scan button starts the set's scan", async () => {
  const calls = renderPage([card("gb", "gb", SCAN)]);
  await userEvent.click(await screen.findByRole("button", { name: "Scan gb" }));
  expect(calls.some((c) => c.url.endsWith("/folders/gb/scan") && c.init?.method === "POST")).toBe(
    true,
  );
  expect(screen.queryByTestId("scan-progress")).toBeNull();
});

test("without a DAT the card offers the default one and holds the scan back", async () => {
  const calls = renderPage([
    {
      ...card("nes", "nes", null),
      needs_dat: true,
      dat_download: { source: "libretro", label: "libretro-database mirror" },
    },
  ]);
  expect(await screen.findByRole("button", { name: "Scan nes" })).toBeDisabled();
  expect(screen.getByTestId("empty-nes")).toHaveTextContent("Please download the DAT first");
  await userEvent.click(screen.getByRole("button", { name: "Download DAT" }));
  expect(
    calls.some(
      (c) => c.url.endsWith("/dats/nes/download?source=libretro") && c.init?.method === "POST",
    ),
  ).toBe(true);
});

test("a set without figures shows a box saying what it waits for, in both views", async () => {
  const folders = [
    { ...card("nodat", "nes", null), needs_dat: true },
    card("new", "gb", null),
    card("empty", "gb", SCAN),
    {
      ...card("full", "gb", SCAN),
      summary: { counts: {}, roms: 1, bytes: 1, identified: 1, unmatched: 0, methods: {} },
    },
  ];
  for (const detail of ["extended", "simplified"]) {
    localStorage.setItem("g1r.home.detail.v1", JSON.stringify(detail));
    renderPage(folders);
    expect(await screen.findByTestId("empty-nodat")).toHaveTextContent(
      "Please upload a DAT in Settings → DATs first",
    );
    expect(screen.getByTestId("empty-new")).toHaveTextContent("Please scan");
    expect(screen.getByTestId("empty-empty")).toHaveTextContent("No ROM files found");
    expect(screen.queryByTestId("empty-full")).toBeNull();
    // The box says it once: no "Not scanned yet" line beside it.
    expect(screen.queryByText("Not scanned yet")).toBeNull();
    cleanup();
  }
});

test("with a DAT there is no download button", async () => {
  renderPage([card("gb", "gb", SCAN)]);
  expect(await screen.findByRole("button", { name: "Scan gb" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Download DAT" })).toBeNull();
});

test("a hint links to where it is acted on, and the card still opens the set", async () => {
  renderPage([
    {
      ...filled(card("nes", "nes", SCAN)),
      warnings: [
        {
          level: "info",
          text: "Unmatched: 3 files. Hasheous may identify some.",
          link: { to: "/settings/lookups", text: "Switch on Hasheous" },
        },
      ],
    },
  ]);
  expect(await screen.findByRole("link", { name: "Switch on Hasheous" })).toHaveAttribute(
    "href",
    "/settings/lookups",
  );
  expect(screen.getByRole("link", { name: META.platforms.nes.name })).toHaveAttribute(
    "href",
    "/folders/nes/matching",
  );
});

test("a card needing conversion opens Conversion, also when it needs matching too", async () => {
  renderPage([
    {
      ...card("nes", "nes", SCAN),
      progress: { processed: 0, to_process: 3, to_match: 2, to_convert: 1 },
    },
    {
      ...card("gb", "gb", SCAN),
      progress: { processed: 0, to_process: 2, to_match: 2, to_convert: 0 },
    },
  ]);
  expect(await screen.findByRole("link", { name: META.platforms.nes.name })).toHaveAttribute(
    "href",
    "/folders/nes/conversion",
  );
  expect(screen.getByRole("link", { name: META.platforms.gb.name })).toHaveAttribute(
    "href",
    "/folders/gb/matching",
  );
});

test("Simplified shows processed, size, to convert and to match with hints, hides the DAT and last scan, and is remembered", async () => {
  const folder: FolderCard = {
    ...card("gb", "gb", SCAN),
    dat: { header_name: "Nintendo - Game Boy", version: "2026.10.07" } as FolderCard["dat"],
    summary: {
      counts: {},
      roms: 10,
      bytes: 3 * 1024 * 1024,
      identified: 9,
      unmatched: 1,
      methods: {},
    },
    progress: { processed: 7, to_process: 3, to_match: 2, to_convert: 1 },
  };
  renderPage([folder]);
  expect(await screen.findByText(/DAT Nintendo - Game Boy/)).toBeInTheDocument();
  expect(screen.getByText("identified")).toBeInTheDocument();
  expect(screen.getByText("folder size").nextSibling).toHaveTextContent("3.0 MiB");
  expect(screen.getByText(/Scanned /)).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Simplified"));
  expect(screen.queryByText(/DAT Nintendo - Game Boy/)).toBeNull();
  expect(screen.queryByText("identified")).toBeNull();
  // Processed and folder size first, then to convert and to match.
  expect(screen.getAllByRole("term").map((t) => t.textContent)).toEqual([
    "processed",
    "folder size",
    "to convert",
    "to match",
  ]);
  expect(screen.getByText("processed").nextSibling).toHaveTextContent("7 / 10");
  expect(screen.getByText("to convert").nextSibling).toHaveTextContent("1");
  expect(screen.getByText("to match").nextSibling).toHaveTextContent("2");
  expect(screen.getByText("folder size").nextSibling).toHaveTextContent("3.0 MiB");
  // jsdom has no ResizeObserver; the tooltip's positioning needs one.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  await userEvent.hover(screen.getByText("to match"));
  expect(await screen.findByRole("tooltip")).toHaveTextContent(/unmatched, or in a game undecided/);
  expect(screen.queryByText(/Scanned /)).toBeNull();
  expect(localStorage.getItem("g1r.home.detail.v1")).toBe(JSON.stringify("simplified"));
});

test("Simplified still shows a running scan", async () => {
  localStorage.setItem("g1r.home.detail.v1", JSON.stringify("simplified"));
  renderPage([
    card("nes", "nes", { ...SCAN, status: "running", finished_at: null, stage: "Listing files" }),
  ]);
  expect(await screen.findByTestId("scan-status-nes")).toHaveTextContent("Listing files");
  // A first scan has no figures yet: it shows in the empty box.
  expect(screen.getByTestId("empty-nes")).toContainElement(screen.getByTestId("scan-status-nes"));
});

test("a set with nothing left to process gets a green border in both views", async () => {
  const filled = (label: string, toProcess: number): FolderCard => ({
    ...card(label, "gb", SCAN),
    summary: { counts: {}, roms: 10, bytes: 0, identified: 10, unmatched: 0, methods: {} },
    progress: {
      processed: 10 - toProcess,
      to_process: toProcess,
      to_match: toProcess,
      to_convert: 0,
    },
  });
  renderPage([filled("done", 0), filled("busy", 2), card("empty", "gb", null)]);
  const doneCard = await screen.findByTestId("folder-card-done");
  for (const view of ["Simplified", "Extended"]) {
    await userEvent.click(screen.getByLabelText(view));
    expect(doneCard).toHaveClass("border-status-good");
    expect(screen.getByTestId("folder-card-busy")).not.toHaveClass("border-status-good");
    expect(screen.getByTestId("folder-card-empty")).not.toHaveClass("border-status-good");
  }
});

test("the badges filter the sets by state, with counts, and are remembered", async () => {
  const filled = (label: string, toMatch: number, toConvert: number): FolderCard => ({
    ...card(label, "gb", SCAN),
    summary: { counts: {}, roms: 10, bytes: 0, identified: 10, unmatched: 0, methods: {} },
    progress: {
      processed: 10 - Math.max(toMatch, toConvert),
      to_process: Math.max(toMatch, toConvert),
      to_match: toMatch,
      to_convert: toConvert,
    },
  });
  renderPage([
    filled("done", 0, 0),
    filled("match", 2, 0),
    filled("convert", 0, 3),
    filled("both", 1, 1),
    card("empty", "gb", null),
  ]);
  const cards = () =>
    screen
      .queryAllByTestId(/^folder-card-/)
      .map((c) => c.dataset.testid?.replace("folder-card-", ""))
      .sort();
  expect(await screen.findByTestId("folder-card-done")).toBeInTheDocument();
  expect(screen.getByTestId("quick-views")).toHaveTextContent(
    "All5Done1Needing conversion2Needing matching2Needing scanning1",
  );
  expect(cards()).toEqual(["both", "convert", "done", "empty", "match"]);
  // Borders and badges share the colour of the state; a set needing both shows conversion.
  const tone = (label: string) => screen.getByTestId(`folder-card-${label}`).dataset.tone;
  expect(["done", "convert", "match", "both", "empty"].map(tone)).toEqual([
    "good",
    "convert",
    "match",
    "convert",
    "unscanned",
  ]);
  expect(screen.getByTestId("folder-card-match")).toHaveClass("border-status-match");
  expect(
    [...screen.getByTestId("quick-views").querySelectorAll("label")].map((l) => l.dataset.tone),
  ).toEqual([undefined, "good", "convert", "match", "unscanned"]);
  const badge = (label: RegExp) => screen.getByLabelText(label);
  await userEvent.click(badge(/^Done/));
  expect(cards()).toEqual(["done"]);
  expect(badge(/^All/)).not.toBeChecked();
  // Badges add up: a set shows when it is in any badge chosen.
  await userEvent.click(badge(/^Needing conversion/));
  expect(cards()).toEqual(["both", "convert", "done"]);
  await userEvent.click(badge(/^Needing scanning/));
  expect(cards()).toEqual(["both", "convert", "done", "empty"]);
  expect(localStorage.getItem("g1r.home.show.v2")).toBe('["done","conversion","unscanned"]');
  // Clicking a chosen badge drops it; dropping the last one is All again.
  await userEvent.click(badge(/^Done/));
  expect(cards()).toEqual(["both", "convert", "empty"]);
  await userEvent.click(badge(/^Needing conversion/));
  await userEvent.click(badge(/^Needing scanning/));
  expect(badge(/^All/)).toBeChecked();
  expect(cards()).toEqual(["both", "convert", "done", "empty", "match"]);
  // All turns the others off.
  await userEvent.click(badge(/^Needing matching/));
  await userEvent.click(badge(/^Done/));
  expect(cards()).toEqual(["both", "done", "match"]);
  await userEvent.click(badge(/^All/));
  expect(cards()).toEqual(["both", "convert", "done", "empty", "match"]);
  expect(
    [badge(/^Done/), badge(/^Needing matching/)].some((b) => (b as HTMLInputElement).checked),
  ).toBe(false);
  expect(localStorage.getItem("g1r.home.show.v2")).toBe('["all"]');
});

test("Needing scanning holds sets never scanned, whose last scan failed, or with a new DAT", async () => {
  renderPage([
    card("never", "gb", null),
    card("failed", "gb", { ...SCAN, status: "failed" }),
    { ...card("newdat", "gb", SCAN), needs_scan: true },
    card("fine", "gb", SCAN),
    card("busy", "gb", { ...SCAN, status: "running" }),
  ]);
  await userEvent.click(await screen.findByLabelText(/^Needing scanning/));
  expect(
    screen
      .queryAllByTestId(/^folder-card-/)
      .map((c) => c.dataset.testid?.replace("folder-card-", ""))
      .sort(),
  ).toEqual(["failed", "never", "newdat"]);
  expect(screen.getByTestId("folder-card-failed")).toHaveAttribute("data-tone", "unscanned");
});

test("a badge with no set says so", async () => {
  localStorage.setItem("g1r.home.show.v2", '["done"]');
  renderPage([
    {
      ...card("busy", "gb", SCAN),
      summary: { counts: {}, roms: 10, bytes: 0, identified: 10, unmatched: 2, methods: {} },
      progress: { processed: 8, to_process: 2, to_match: 2, to_convert: 0 },
    },
  ]);
  expect(await screen.findByText("No set here")).toBeInTheDocument();
  expect(screen.getByText(/No set is done right now/)).toBeInTheDocument();
  expect(screen.queryByTestId("folder-card-busy")).toBeNull();
  expect(screen.queryByText("No sets yet")).toBeNull();
});

test("warnings sit in a two-line slot, most severe first, in full on hover", async () => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  renderPage([
    {
      ...filled(card("nes", "nes", SCAN)),
      warnings: [
        { level: "warn", text: "Not NES ROMs or archives: 2 files.", link: null },
        { level: "bad", text: "The last scan failed: a long reason.", link: null },
      ],
    },
    filled(card("gb", "gb", SCAN)),
  ]);
  const slot = await screen.findByTestId("warnings-nes");
  expect(slot).toHaveClass("line-clamp-2", "h-8");
  expect(slot.textContent).toBe(
    "The last scan failed: a long reason. Not NES ROMs or archives: 2 files. ",
  );
  // A set without warnings keeps the slot, empty, so the cards have one size.
  expect(screen.getByTestId("warnings-gb")).toHaveClass("h-8");
  expect(screen.getByTestId("warnings-gb")).toBeEmptyDOMElement();
  await userEvent.hover(slot);
  expect(await screen.findByRole("tooltip")).toHaveTextContent(
    "The last scan failed: a long reason.Not NES ROMs or archives: 2 files.",
  );
});
