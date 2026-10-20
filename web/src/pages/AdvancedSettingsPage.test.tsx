import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { queryClient } from "@/lib/queries";
import { AdvancedSettingsPage } from "./SettingsPages";

test("parallel scans sit above the configuration and save within the most allowed", async () => {
  const sent: unknown[] = [];
  vi.stubGlobal("fetch", async (_url: string, init?: RequestInit) => {
    if (init?.method === "PUT") sent.push(JSON.parse(String(init.body)));
    return new Response(
      JSON.stringify({
        parallel_scans: { value: 4, default: 4, max: 16 },
        igir_threads: { value: null, default_readers: 6, default_pool: 4, max: 64 },
        effective_yaml: "jobs:\n  scan_workers: 4\n",
        library_file: "/data/library.yaml",
      }),
    );
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AdvancedSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
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
  await vi.waitFor(() => expect(sent).toEqual([{ value: 2 }]));
});

test("igir threads start at igir's own and save a chosen number", async () => {
  const sent: unknown[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") sent.push([url, JSON.parse(String(init.body))]);
    return new Response(
      JSON.stringify({
        parallel_scans: { value: 4, default: 4, max: 16 },
        igir_threads: { value: null, default_readers: 6, default_pool: 4, max: 64 },
        effective_yaml: "",
        library_file: "/data/library.yaml",
      }),
    );
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AdvancedSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const input = await screen.findByLabelText("igir threads");
  expect(input).toHaveValue(6);
  expect(screen.getByText(/igir's own \(6 files at once, a pool of 4\)/)).toBeInTheDocument();
  await userEvent.clear(input);
  await userEvent.type(input, "2");
  await userEvent.click(screen.getByRole("button", { name: "Save igir threads" }));
  await vi.waitFor(() => expect(sent).toEqual([["/api/settings/igir-threads", { value: 2 }]]));
});
