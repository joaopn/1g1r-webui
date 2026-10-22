import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { queryClient } from "@/lib/queries";
import type { Scan } from "@/lib/types";
import { ScanPanel } from "./ScanPanel";

const SCAN = {
  id: 1,
  kind: "identify",
  folder_label: "nes",
  status: "done",
  message: "2 of 3 ROM files identified",
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
function renderPanelWith(scan: Scan | null, lastScan: Scan | null) {
  const posted: string[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") posted.push(url);
    return new Response(JSON.stringify({}), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <ScanPanel label="nes" kind="identify" scan={scan} lastScan={lastScan} title="Matching">
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

test("a folder never scanned has one button", () => {
  renderPanel(null);
  expect(screen.getByRole("button", { name: /Scan folder/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Full scan/ })).not.toBeInTheDocument();
});

test("on the Conversion page the panel checks the files, with no full variant", async () => {
  const posted: string[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") posted.push(url);
    return new Response(JSON.stringify({}), { status: 200 });
  });
  queryClient.clear();
  const check = { ...SCAN, kind: "check", message: "5 ROM files checked; 1 to convert" } as Scan;
  render(
    <QueryClientProvider client={queryClient}>
      <ScanPanel label="nes" kind="check" scan={check} title="Check files">
        Target
      </ScanPanel>
    </QueryClientProvider>,
  );
  expect(screen.getByText(/^Checked .*: 5 ROM files checked; 1 to convert\.$/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Full scan/ })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Check files/ }));
  expect(posted).toEqual(["/api/folders/nes/check"]);
});

test("on the Matching page a check is not reported as the last scan", () => {
  renderPanelWith({ ...SCAN, kind: "check" } as Scan, null);
  expect(screen.getByText("Not scanned yet.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Scan folder/ })).toBeInTheDocument();
});
