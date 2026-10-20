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
  const save = screen.getByRole("button", { name: "Save" });
  await userEvent.clear(input);
  await userEvent.type(input, "17");
  expect(save).toBeDisabled();
  await userEvent.clear(input);
  await userEvent.type(input, "2");
  await userEvent.click(save);
  await vi.waitFor(() => expect(sent).toEqual([{ value: 2 }]));
});
