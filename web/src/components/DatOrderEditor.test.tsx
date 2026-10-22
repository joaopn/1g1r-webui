import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { queryClient } from "@/lib/queries";
import type { DatOrderEntry, DatVersion } from "@/lib/types";
import { DatOrderEditor } from "./DatOrderEditor";

const dat = (source: string, header: string) =>
  ({ id: header.length, source, header_name: header, version: "1", sha1: source }) as DatVersion;

const ENTRIES: DatOrderEntry[] = [
  {
    id: "nointro",
    label: "No-Intro (DAT-o-MATIC)",
    on: true,
    lookup: false,
    dat: dat("nointro", "Commodore - Amiga"),
    pinned: false,
  },
  {
    id: "libretro",
    label: "libretro-database mirror",
    on: true,
    lookup: false,
    dat: dat("libretro", "Commodore - Amiga (libretro)"),
    pinned: false,
  },
  { id: "hasheous", label: "Hasheous", on: true, lookup: true, dat: null, pinned: false },
];

test("moving and switching off entries saves the platform's order", async () => {
  const sent: unknown[] = [];
  vi.stubGlobal("fetch", async (_url: string, init?: RequestInit) => {
    if (init?.method === "PUT") sent.push(JSON.parse(String(init.body)));
    return new Response(JSON.stringify([]), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <DatOrderEditor platform="amiga" platformName="Amiga" entries={ENTRIES} />
    </QueryClientProvider>,
  );
  await userEvent.click(screen.getByTestId("dat-order-button"));
  await userEvent.click(screen.getByRole("button", { name: "Move Hasheous up" }));
  const libretro = screen.getByRole("checkbox", { name: "Use libretro-database mirror" });
  // The text next to it is the entry's state, not the action.
  expect(libretro).toBeChecked();
  expect(libretro.parentElement).toHaveTextContent("on");
  await userEvent.click(libretro);
  expect(libretro).not.toBeChecked();
  expect(libretro.parentElement).toHaveTextContent("off");
  await userEvent.click(screen.getByRole("button", { name: "Save order" }));
  await vi.waitFor(() =>
    expect(sent).toEqual([{ order: ["nointro", "hasheous", "libretro"], off: ["libretro"] }]),
  );
});
