import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { queryClient } from "@/lib/queries";
import type { Run } from "@/lib/types";
import { META } from "@/test/fixtures";
import { RunPanel } from "./RunPanel";

const RUN: Run = {
  id: 7,
  folder_label: "psx",
  kind: "apply",
  scope: "convert",
  status: "running",
  total: 10,
  done: 4,
  stopping: false,
  message: "",
  started_at: "2026-10-21T10:00:00Z",
  finished_at: null,
  failed: [],
  warnings: [],
  waiting_for: null,
};

function renderPanel(run: Run, onMove?: (relPaths: string[]) => void) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(run), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <RunPanel label="psx" meta={META} onMove={onMove} />
    </QueryClientProvider>,
  );
  return calls;
}

test("a running conversion has a Stop button that stops it", async () => {
  const calls = renderPanel(RUN);
  await userEvent.click(await screen.findByRole("button", { name: "Stop the conversion of psx" }));
  expect(
    calls.some((c) => c.url.endsWith("/folders/psx/convert/stop") && c.init?.method === "POST"),
  ).toBe(true);
});

test("a stopping conversion says so and cannot be stopped again", async () => {
  renderPanel({ ...RUN, stopping: true });
  expect(await screen.findByText(/Conversion stopping: 4 of 10 steps/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Stop the conversion of psx" })).toBeDisabled();
});

test("other runs have no Stop button", async () => {
  renderPanel({ ...RUN, scope: "" });
  expect(await screen.findByText(/Apply running/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Stop/ })).toBeNull();
});

test("a conversion waiting for another folder's says which, and can still be stopped", async () => {
  renderPanel({ ...RUN, done: 0, waiting_for: "3ds" });
  expect(await screen.findByText("Waiting for the conversion of 3ds")).toBeInTheDocument();
  expect(screen.queryByText(/Conversion running/)).toBeNull();
  expect(screen.getByRole("button", { name: "Stop the conversion of psx" })).toBeEnabled();
});

test("a finished conversion offers to move the files it could not convert", async () => {
  const moved: string[][] = [];
  renderPanel(
    {
      ...RUN,
      status: "failed",
      finished_at: "2026-10-21T11:00:00Z",
      message: "1 file converted; 2 failed",
      failed: [
        { rel_path: "a.3ds", error: "a.3ds is cut short", action: "convert" },
        { rel_path: "b.3ds", error: "b.3ds is damaged", action: "convert" },
        { rel_path: "c.3ds", error: "kept", action: "delete" },
      ],
    },
    (relPaths) => moved.push(relPaths),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: "Move failed to discarded/ (2 files)" }),
  );
  expect(moved).toEqual([["a.3ds", "b.3ds"]]);
});

test("a running conversion offers no move yet", async () => {
  renderPanel({ ...RUN, failed: [{ rel_path: "a.3ds", error: "x", action: "convert" }] }, () => {});
  expect(await screen.findByText(/Conversion running/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Move failed/ })).toBeNull();
});

test("a finished conversion lists the files converted with a warning", async () => {
  renderPanel({
    ...RUN,
    status: "done",
    finished_at: "2026-10-21T11:00:00Z",
    message: "2 files converted (1 with a warning)",
    warnings: [
      {
        rel_path: "A.7z",
        warning: "A (Track 2).bin padded with 1072 zero bytes to a whole CD sector",
      },
    ],
  });
  expect(
    await screen.findByText(
      "A.7z: A (Track 2).bin padded with 1072 zero bytes to a whole CD sector",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/restore the original from Discarded or remove the file/),
  ).toBeInTheDocument();
});
