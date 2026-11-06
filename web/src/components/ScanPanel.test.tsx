import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { queryClient } from "@/lib/queries";
import type { Scan, TerminalLine } from "@/lib/types";
import { ScanPanel } from "./ScanPanel";

const SCAN = {
  id: 1,
  kind: "identify",
  folder_label: "nes",
  status: "done",
  message: "2 of 3 ROM files identified",
  changes: null,
  started_at: "2026-10-19T09:00:00Z",
  finished_at: "2026-10-19T09:01:00Z",
  stage: null,
  files_done: null,
  files_total: null,
} as unknown as Scan;

function renderPanel(scan: Scan | null) {
  return renderPanelWith(scan, scan);
}

/** The Matching page's panel: the latest run of either kind, and the latest Scan. */
function renderPanelWith(scan: Scan | null, lastScan: Scan | null, blocked?: string) {
  const posted: string[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") posted.push(url);
    return new Response(JSON.stringify({}), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <ScanPanel
        label="nes"
        kind="identify"
        scan={scan}
        lastScan={lastScan}
        title="Matching"
        blocked={blocked}
      >
        DAT
      </ScanPanel>
    </QueryClientProvider>,
  );
  return posted;
}

test("a quick scan reuses earlier reads; a full scan asks for every file again", async () => {
  const posted = renderPanel(SCAN);
  expect(screen.getByRole("heading", { name: "Matching" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Quick scan/ }));
  await userEvent.click(screen.getByRole("button", { name: /Full scan/ }));
  expect(posted).toEqual(["/api/folders/nes/scan", "/api/folders/nes/scan?full=true"]);
});

test("a scan waits while files are not converted, and says why", () => {
  renderPanelWith(SCAN, SCAN, "Convert or discard first: 2 files");
  for (const name of [/Quick scan/, /Full scan/]) {
    const button = screen.getByRole("button", { name });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Convert or discard first: 2 files");
  }
});

test("a folder never scanned has one button", () => {
  renderPanel(null);
  expect(screen.getByRole("button", { name: /Scan folder/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Full scan/ })).not.toBeInTheDocument();
});

test("on the Conversion page the panel reports the last check and has no run button", () => {
  queryClient.clear();
  const check = { ...SCAN, kind: "check", message: "5 ROM files checked; 1 to convert" } as Scan;
  render(
    <QueryClientProvider client={queryClient}>
      <ScanPanel label="nes" kind="check" scan={check} title="Target format">
        Target
      </ScanPanel>
    </QueryClientProvider>,
  );
  expect(screen.getByText(/^Checked .*: 5 ROM files checked; 1 to convert\.$/)).toBeInTheDocument();
  // Check files sits in the set's header.
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

test("on the Matching page a check is not reported as the last scan", () => {
  renderPanelWith({ ...SCAN, kind: "check" } as Scan, null);
  expect(screen.getByText("Not scanned yet.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Scan folder/ })).toBeInTheDocument();
});

test("a running scan fills the panel's background as it goes", () => {
  const running = {
    ...SCAN,
    status: "running",
    finished_at: null,
    stage: "Matching checksums",
    files_done: 30,
    files_total: 120,
  } as unknown as Scan;
  renderPanel(running);
  expect(screen.getByTestId("scan-progress")).toHaveStyle({ transform: "scaleX(0.25)" });
});

const FIRST = "igir report \\\n  --dat /data/dats/nes/a.dat \\\n  --input /roms/nes";
const SECOND = "igir report \\\n  --dat /data/dats/nes/b.dat \\\n  --input /roms/nes";

const DONE: TerminalLine = [
  [" ", ""],
  ["✓", "green"],
  [" Parsing DATs ", ""],
  ["»", "faint"],
  [" 1 DAT found", ""],
];
const BAR: TerminalLine = [
  ["   ", ""],
  ["■", "cyan"],
  ["■", "gray"],
  ["■", "dark"],
  [" 1/3", ""],
];

test("while igir runs its command shows, marked, open until closed", async () => {
  renderPanel({
    ...SCAN,
    status: "running",
    finished_at: null,
    stage: "Matching checksums with igir",
    command: SECOND,
    commands: [
      { command: FIRST, output: [DONE] },
      { command: SECOND, output: [DONE, BAR] },
    ],
  } as Scan);
  const details = screen.getByTestId("scan-command");
  expect(details).toHaveAttribute("open");
  expect(screen.getByText("igir is running")).toBeInTheDocument();
  const pre = details.querySelector("pre");
  expect(pre).toHaveTextContent("$ igir report \\ --dat /data/dats/nes/a.dat");
  expect(pre).toHaveTextContent(/a\.dat \\ --input \/roms\/nes ✓ Parsing DATs » 1 DAT found\$/);
  expect(pre).toHaveTextContent(
    /b\.dat \\ --input \/roms\/nes ✓ Parsing DATs » 1 DAT found ■■■ 1\/3running…$/,
  );
  // A bar's parts are told apart by colour only: each keeps igir's.
  const parts = [...(pre?.querySelectorAll("span") ?? [])].filter((s) => s.textContent === "■");
  expect(parts.map((part) => part.className).slice(-3)).toEqual([
    "text-terminal-cyan",
    "text-terminal-gray",
    "text-terminal-dark",
  ]);
  expect(screen.getAllByText("»")[0]).toHaveClass("opacity-60");
  await userEvent.click(screen.getByText("igir is running"));
  expect(details).not.toHaveAttribute("open");
});

test("a finished scan keeps its igir commands, unmarked", () => {
  renderPanel({ ...SCAN, commands: [{ command: FIRST, output: [] }] } as Scan);
  expect(screen.getByText("igir commands of the last scan")).toBeInTheDocument();
  expect(screen.getByTestId("scan-command")).not.toHaveTextContent("running…");
});

test("a running Check files leaves the last scan's commands", () => {
  const check = { ...SCAN, kind: "check", status: "running", stage: "Listing files" } as Scan;
  renderPanelWith(check, { ...SCAN, commands: [{ command: FIRST, output: [] }] } as Scan);
  expect(screen.getByText("igir commands of the last scan")).toBeInTheDocument();
});

test("a scan that ran no igir shows no commands", () => {
  renderPanel({ ...SCAN, commands: [] } as Scan);
  expect(screen.queryByTestId("scan-command")).toBeNull();
});

test("a scan of unknown length pulses", () => {
  renderPanel({ ...SCAN, status: "running", finished_at: null, stage: "Listing" } as Scan);
  expect(screen.getByTestId("scan-progress")).toHaveClass("animate-pulse");
});

test("a finished scan has no bar", () => {
  renderPanel(SCAN);
  expect(screen.queryByTestId("scan-progress")).toBeNull();
});
