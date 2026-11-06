import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { keys, queryClient } from "@/lib/queries";
import { AdvancedSettingsPage } from "./SettingsPages";

/** Answers every request with these settings; returns the PUTs sent, as [url, body]. */
function stubSettings(changes: Record<string, unknown> = {}) {
  const sent: unknown[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") sent.push([url, JSON.parse(String(init.body))]);
    return new Response(
      JSON.stringify({
        parallel_scans: { value: 4, default: 4, max: 16 },
        parallel_conversions: { value: 2, default: 2, max: 8 },
        page_size: { value: 50, default: 50, max: 1000 },
        auto_check_minutes: { value: 1440, default: 1440, max: 525600 },
        igir_threads: { value: null, default_readers: 6, default_pool: 4, max: 64 },
        effective_yaml: "",
        library_file: "/data/library.yaml",
        ...changes,
      }),
    );
  });
  return sent;
}

function renderPage() {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AdvancedSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("parallel scans sit above the configuration and save within the most allowed", async () => {
  const sent = stubSettings({ effective_yaml: "jobs:\n  scan_workers: 4\n" });
  queryClient.clear();
  renderPage();
  const input = await screen.findByLabelText("Parallel scans");
  expect(
    input.compareDocumentPosition(screen.getByText(/scan_workers: 4/)) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  const save = screen.getByRole("button", { name: "Save parallel scans" });
  expect(save).toBeDisabled();
  await userEvent.clear(input);
  await userEvent.type(input, "17");
  expect(save).toBeDisabled();
  await userEvent.clear(input);
  await userEvent.type(input, "2");
  await userEvent.click(save);
  await vi.waitFor(() => expect(sent).toEqual([["/api/settings/parallel-scans", { value: 2 }]]));
});

test("igir threads start at igir's own and save a chosen number", async () => {
  const sent = stubSettings();
  queryClient.clear();
  renderPage();
  const input = await screen.findByLabelText("igir threads");
  expect(input).toHaveValue(6);
  expect(screen.getByText(/igir's own \(6 files at once, a pool of 4\)/)).toBeInTheDocument();
  await userEvent.clear(input);
  await userEvent.type(input, "2");
  await userEvent.click(screen.getByRole("button", { name: "Save igir threads" }));
  await vi.waitFor(() => expect(sent).toEqual([["/api/settings/igir-threads", { value: 2 }]]));
});

test("parallel conversions save to their own setting", async () => {
  const sent = stubSettings();
  queryClient.clear();
  renderPage();
  const input = await screen.findByLabelText("Parallel conversions");
  expect(input).toHaveValue(2);
  const save = screen.getByRole("button", { name: "Save parallel conversions" });
  await userEvent.clear(input);
  await userEvent.type(input, "9");
  expect(save).toBeDisabled();
  await userEvent.clear(input);
  await userEvent.type(input, "3");
  await userEvent.click(save);
  await vi.waitFor(() =>
    expect(sent).toEqual([["/api/settings/parallel-conversions", { value: 3 }]]),
  );
});

test("rows per page show the saved number, save a chosen one and go back to the default", async () => {
  const sent = stubSettings({ page_size: { value: 100, default: 50, max: 1000 } });
  queryClient.clear();
  queryClient.setQueryData(keys.meta, {});
  renderPage();
  const input = await screen.findByLabelText("Rows per page");
  expect(input).toHaveValue(100);
  const section = input.closest("section") as HTMLElement;
  expect(section).toHaveTextContent("Default 50, at most 1000.");
  const save = within(section).getByRole("button", { name: "Save rows per page" });
  expect(save).toBeDisabled();
  await userEvent.clear(input);
  await userEvent.type(input, "1001");
  expect(save).toBeDisabled();
  await userEvent.clear(input);
  await userEvent.type(input, "25");
  await userEvent.click(save);
  await vi.waitFor(() => expect(sent).toEqual([["/api/settings/page-size", { value: 25 }]]));
  // Every table reads the number from the app's meta, which a save refreshes.
  await vi.waitFor(() => expect(queryClient.getQueryState(keys.meta)?.isInvalidated).toBe(true));
  await userEvent.click(within(section).getByRole("button", { name: "Use the default" }));
  await vi.waitFor(() => expect(sent).toHaveLength(2));
  expect(sent[1]).toEqual(["/api/settings/page-size", { value: null }]);
});

test("the auto-check interval is in minutes, once a day by default", async () => {
  const sent = stubSettings();
  queryClient.clear();
  renderPage();
  const input = await screen.findByLabelText("Auto-check minutes");
  expect(input).toHaveValue(1440);
  const section = input.closest("section") as HTMLElement;
  expect(section).toHaveTextContent("Default 1440 (once a day), at most 525600.");
  await userEvent.clear(input);
  await userEvent.type(input, "60");
  await userEvent.click(within(section).getByRole("button", { name: "Save auto-check minutes" }));
  await vi.waitFor(() => expect(sent).toEqual([["/api/settings/auto-check", { value: 60 }]]));
});
