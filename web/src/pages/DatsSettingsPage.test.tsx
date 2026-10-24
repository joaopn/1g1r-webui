import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { queryClient } from "@/lib/queries";
import type { DatRow, DatVersion, Meta } from "@/lib/types";
import { META } from "@/test/fixtures";
import { DatsSettingsPage } from "./SettingsPages";

const MULTI: Meta = {
  ...META,
  dat_sources: {
    ...META.dat_sources,
    nointro: {
      label: "No-Intro (DAT-o-MATIC)",
      short_label: "No-Intro",
      identification_only: false,
    },
    redump: { label: "redump.info", short_label: "Redump", identification_only: false },
  },
};

const version = (id: number, platform: string, source: string): DatVersion => ({
  id,
  platform,
  source,
  header_name: `${platform} DAT`,
  version: null,
  sha1: `${id}`,
  game_count: 1,
  has_parent_clone: 0,
  matches_platform: 1,
  added_at: "2026-10-20T00:00:00Z",
});

const row = (platform: string, versions: DatVersion[]): DatRow => ({
  platform,
  active: versions[0] ?? null,
  order: [],
  own_order: false,
  versions,
  folders: [],
  downloads: [],
  titledb: platform === "switch",
});

function renderPage() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (init?.method === "DELETE") {
      return new Response(JSON.stringify({ versions: 3, platforms: ["gb", "nes"] }));
    }
    const body = url.endsWith("/meta")
      ? MULTI
      : url.endsWith("/dats")
        ? [
            row("nes", [version(1, "nes", "nointro"), version(2, "nes", "nointro")]),
            row("gb", [version(3, "gb", "nointro"), version(4, "gb", "libretro")]),
            row("switch", [version(5, "switch", "titledb:US.en")]),
          ]
        : url.endsWith("/titledb/files")
          ? ["GB.en", "JP.en", "JP.ja", "US.en"]
          : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DatsSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

test("Remove DATs: one button per stored source, each removing it after a confirmation", async () => {
  const calls = renderPage();
  const box = await screen.findByRole("region", { name: "Remove DATs" });
  const buttons = within(box).getAllByRole("button");
  // Redump has no stored DAT: no button.
  expect(buttons.map((b) => b.textContent?.trim())).toEqual([
    "libretro· 1 DAT",
    "No-Intro· 3 DATs",
    "titledb· 1 DAT",
  ]);

  await userEvent.click(buttons[1]);
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("Remove every No-Intro (DAT-o-MATIC) DAT?");
  expect(dialog).toHaveTextContent("3 DATs on 2 platforms");
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);

  await userEvent.click(within(dialog).getByRole("button", { name: "Remove 3 DATs" }));
  const removal = calls.find((c) => c.init?.method === "DELETE");
  expect(removal?.url).toMatch(/\/dats\/sources\/nointro$/);
});

test("titledb: a button per featured region file, any other picked from the list", async () => {
  const calls = renderPage();
  const box = await screen.findByTestId("titledb-switch");
  // Only the title-ID platform offers it.
  expect(screen.queryByTestId("titledb-nes")).toBeNull();
  await userEvent.click(within(box).getByRole("button", { name: /JP\.en/ }));
  expect(calls.some((c) => c.url.endsWith("/dats/switch/titledb?file=JP.en"))).toBe(true);

  // The list is read from titledb only once it is opened.
  expect(calls.some((c) => c.url.endsWith("/titledb/files"))).toBe(false);
  const select = within(box).getByRole("combobox");
  await userEvent.click(select);
  await within(box).findByRole("option", { name: "JP.ja" });
  expect(within(box).queryByRole("option", { name: "US.en" })).toBeNull();
  const download = within(box).getByRole("button", { name: "Download the chosen file" });
  expect(download).toBeDisabled();
  await userEvent.selectOptions(select, "GB.en");
  await userEvent.click(within(box).getByRole("button", { name: "Download GB.en" }));
  expect(calls.some((c) => c.url.endsWith("/dats/switch/titledb?file=GB.en"))).toBe(true);
});
