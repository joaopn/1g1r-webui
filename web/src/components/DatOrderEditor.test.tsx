import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
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
    own_off: false,
    global_off: false,
    lookup: false,
    dat: dat("nointro", "Commodore - Amiga"),
    pinned: false,
  },
  {
    id: "libretro",
    label: "libretro-database mirror",
    on: true,
    own_off: false,
    global_off: false,
    lookup: false,
    dat: dat("libretro", "Commodore - Amiga (libretro)"),
    pinned: false,
  },
  {
    id: "hasheous",
    label: "Hasheous",
    on: true,
    own_off: false,
    global_off: false,
    lookup: true,
    dat: null,
    pinned: false,
  },
];

const show = (entries: DatOrderEntry[]) =>
  render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <DatOrderEditor platform="amiga" platformName="Amiga" entries={entries} />
      </QueryClientProvider>
    </MemoryRouter>,
  );

const stubPut = () => {
  const sent: unknown[] = [];
  vi.stubGlobal("fetch", async (_url: string, init?: RequestInit) => {
    if (init?.method === "PUT") sent.push(JSON.parse(String(init.body)));
    return new Response(JSON.stringify([]), { status: 200 });
  });
  queryClient.clear();
  return sent;
};

test("moving and switching off entries saves the platform's order", async () => {
  const sent = stubPut();
  show(ENTRIES);
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

test("an entry off on every platform is not switched here, and stays out of the platform's own", async () => {
  const sent = stubPut();
  show(ENTRIES.map((e) => (e.id === "libretro" ? { ...e, on: false, global_off: true } : e)));
  await userEvent.click(screen.getByTestId("dat-order-button"));
  expect(screen.queryByRole("checkbox", { name: "Use libretro-database mirror" })).toBeNull();
  expect(screen.getByRole("link", { name: "off" })).toHaveAttribute(
    "href",
    "/settings/dat-sources",
  );
  await userEvent.click(screen.getByRole("button", { name: "Save order" }));
  await vi.waitFor(() =>
    expect(sent).toEqual([{ order: ["nointro", "libretro", "hasheous"], off: [] }]),
  );
});
