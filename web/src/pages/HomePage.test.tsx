import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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
  counts: {},
  reclaim_bytes: 0,
  conversion: { to_convert: 0, flagged: 0 } as FolderCard["conversion"],
  progress: { processed: 0, to_process: 0 },
  discarded: { files: 0, bytes: 0 },
  warnings: [],
});

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
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
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
  expect(screen.getByText("Download the DAT first")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Download DAT" }));
  expect(
    calls.some(
      (c) => c.url.endsWith("/dats/nes/download?source=libretro") && c.init?.method === "POST",
    ),
  ).toBe(true);
});

test("with a DAT there is no download button", async () => {
  renderPage([card("gb", "gb", SCAN)]);
  expect(await screen.findByRole("button", { name: "Scan gb" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "Download DAT" })).toBeNull();
});

test("a hint links to where it is acted on, and the card still opens the set", async () => {
  renderPage([
    {
      ...card("nes", "nes", SCAN),
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

test("Simplified shows processed, to process and size, hides the DAT and last scan, and is remembered", async () => {
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
    progress: { processed: 7, to_process: 3 },
  };
  renderPage([folder]);
  expect(await screen.findByText(/DAT Nintendo - Game Boy/)).toBeInTheDocument();
  expect(screen.getByText("identified")).toBeInTheDocument();
  expect(screen.getByText("folder size").nextSibling).toHaveTextContent("3.0 MiB");
  expect(screen.getByText(/Scanned /)).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Simplified"));
  expect(screen.queryByText(/DAT Nintendo - Game Boy/)).toBeNull();
  expect(screen.queryByText("identified")).toBeNull();
  expect(screen.getByText("processed").nextSibling).toHaveTextContent("7");
  expect(screen.getByText("to process").nextSibling).toHaveTextContent("3");
  expect(screen.getByText("folder size").nextSibling).toHaveTextContent("3.0 MiB");
  expect(screen.queryByText(/Scanned /)).toBeNull();
  expect(localStorage.getItem("g1r.home.detail.v1")).toBe(JSON.stringify("simplified"));
});

test("Simplified still shows a running scan", async () => {
  localStorage.setItem("g1r.home.detail.v1", JSON.stringify("simplified"));
  renderPage([
    card("nes", "nes", { ...SCAN, status: "running", finished_at: null, stage: "Listing files" }),
  ]);
  expect(await screen.findByTestId("scan-status-nes")).toHaveTextContent("Listing files");
});
