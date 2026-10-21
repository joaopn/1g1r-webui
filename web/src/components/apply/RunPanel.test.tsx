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
};

function renderPanel(run: Run) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(run), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <RunPanel label="psx" meta={META} />
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
