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
          ]
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
