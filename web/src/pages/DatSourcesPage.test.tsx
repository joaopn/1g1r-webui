import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { queryClient } from "@/lib/queries";
import type { DatSource } from "@/lib/types";
import { DatSourcesPage } from "./DatSourcesPage";

const source = (id: string, label: string, extra: Partial<DatSource> = {}): DatSource => ({
  id,
  label,
  short_label: id,
  lookup: false,
  side: false,
  on: true,
  every: false,
  platforms: [],
  ...extra,
});

const SOURCES: DatSource[] = [
  source("nointro", "No-Intro (DAT-o-MATIC)", {
    platforms: [
      { platform: "nes", dat_name: null },
      { platform: "gb", dat_name: null },
    ],
  }),
  source("upload", "Uploaded file", { every: true }),
  source("libretro", "libretro-database mirror", {
    platforms: [{ platform: "nes", dat_name: null }],
  }),
  source("nonredump", "No-Intro Non-Redump (DAT-o-MATIC)", {
    side: true,
    platforms: [
      { platform: "psx", dat_name: "Non-Redump - Sony - PlayStation" },
      { platform: "saturn", dat_name: "Non-Redump - Sega - Sega Saturn" },
    ],
  }),
  source("hasheous", "Hasheous", { lookup: true, every: true }),
  source("titledb", "titledb (GitHub)", {
    side: true,
    platforms: [{ platform: "switch", dat_name: null }],
  }),
];

const META = {
  platforms: {
    nes: { name: "NES", short: "NES", kind: "console" },
    gb: { name: "Game Boy", short: "GB", kind: "handheld" },
    psx: { name: "PlayStation", short: "PS1", kind: "console" },
    saturn: { name: "Saturn", short: "SAT", kind: "console" },
    switch: { name: "Switch", short: "NSW", kind: "console" },
  },
  ui: { platform_icon_width_rem: 3 },
};

const DATS = [
  { platform: "psx", folders: ["psx"] },
  { platform: "saturn", folders: [] },
  { platform: "switch", folders: ["switch"] },
];

const stub = (sent: unknown[] = []) => {
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body));
      sent.push(body);
      return new Response(
        JSON.stringify(SOURCES.map((s) => ({ ...s, on: !body.off.includes(s.id) }))),
      );
    }
    if (url.endsWith("/dat-sources")) return new Response(JSON.stringify(SOURCES));
    if (url.endsWith("/meta")) return new Response(JSON.stringify(META));
    if (url.endsWith("/dats")) return new Response(JSON.stringify(DATS));
    return new Response(JSON.stringify({ lookups: { hasheous: false } }));
  });
  queryClient.clear();
  return sent;
};

const show = (path = "/settings/dat-sources") =>
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <DatSourcesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

test("Multiplatform lists the general sources with the platforms each serves", async () => {
  const sent = stub();
  show();
  const libretro = await screen.findByTestId("source-libretro");
  expect(within(libretro).getByText(/One file per game/)).toBeInTheDocument();
  expect(
    await within(screen.getByTestId("platforms-nointro")).findByTitle("Game Boy"),
  ).toBeInTheDocument();
  expect(
    within(screen.getByTestId("platforms-upload")).getByText("Every platform"),
  ).toBeInTheDocument();
  expect(screen.queryByTestId("source-nonredump")).toBeNull();
  // Online lookups are switched in their own settings page.
  const hasheous = screen.getByTestId("source-hasheous");
  expect(within(hasheous).getByRole("link", { name: "off in Online lookups" })).toBeInTheDocument();
  expect(within(hasheous).queryByRole("checkbox")).toBeNull();
  await userEvent.click(screen.getByLabelText("Use libretro-database mirror"));
  await vi.waitFor(() => expect(sent).toEqual([{ off: ["libretro"] }]));
  expect(await screen.findByLabelText("Use libretro-database mirror")).not.toBeChecked();
});

test("Single platform lists each platform's own DATs, platforms with a set first", async () => {
  const sent = stub();
  show("/settings/dat-sources?tab=single");
  const nonredump = await screen.findByTestId("source-nonredump");
  expect(screen.getByRole("tab", { name: "Single platform" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(await within(nonredump).findByText("Non-Redump - Sony - PlayStation")).toBeInTheDocument();
  expect(within(nonredump).queryByText("Saturn")).toBeNull();
  expect(
    within(screen.getByTestId("source-titledb")).getByText(/One file per eShop region/),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText(/All platforms/));
  expect(within(nonredump).getByText("Saturn")).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Use titledb (GitHub)"));
  await vi.waitFor(() => expect(sent).toEqual([{ off: ["titledb"] }]));
});

test("the questions and answers start collapsed", async () => {
  stub();
  show();
  const faq = await screen.findByTestId("dat-faq");
  expect(faq).not.toHaveAttribute("open");
  expect(within(faq).getByText(/libretro-database mirror\?/)).toBeInTheDocument();
});
