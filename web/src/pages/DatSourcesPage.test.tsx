import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { queryClient } from "@/lib/queries";
import { DatSourcesPage } from "./DatSourcesPage";

const ORDER = {
  own: false,
  entries: [
    { id: "nointro", label: "No-Intro (DAT-o-MATIC)", on: true, lookup: false },
    { id: "libretro", label: "libretro-database mirror", on: true, lookup: false },
    { id: "hasheous", label: "Hasheous", on: true, lookup: true },
  ],
};

test("explains each source and saves the global order", async () => {
  const sent: unknown[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") sent.push(JSON.parse(String(init.body)));
    if (url.endsWith("/dat-order")) return new Response(JSON.stringify(ORDER));
    return new Response(JSON.stringify({ lookups: { hasheous: false, screenscraper: false } }));
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DatSourcesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const libretro = await screen.findByTestId("source-libretro");
  expect(within(libretro).getByText(/One file per game/)).toBeInTheDocument();
  expect(
    within(screen.getByTestId("source-hasheous")).getByText("switched off in Online lookups"),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Move libretro-database mirror up" }));
  await userEvent.click(screen.getByLabelText("Use Hasheous"));
  await userEvent.click(screen.getByRole("button", { name: "Save order" }));
  await vi.waitFor(() =>
    expect(sent).toEqual([{ order: ["libretro", "nointro", "hasheous"], off: ["hasheous"] }]),
  );
});

test("the questions and answers start collapsed", async () => {
  vi.stubGlobal("fetch", async (url: string) =>
    url.endsWith("/dat-order")
      ? new Response(JSON.stringify(ORDER))
      : new Response(JSON.stringify({ lookups: { hasheous: true, screenscraper: true } })),
  );
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DatSourcesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const faq = await screen.findByTestId("dat-faq");
  expect(faq).not.toHaveAttribute("open");
  expect(within(faq).getByText(/libretro-database mirror\?/)).toBeInTheDocument();
});
