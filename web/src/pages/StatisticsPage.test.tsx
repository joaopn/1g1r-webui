import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { queryClient } from "@/lib/queries";
import type { Missing, Statistics } from "@/lib/types";
import { META } from "@/test/fixtures";
import { StatisticsPage } from "./StatisticsPage";

const DAT = {
  id: 1,
  platform: "nes",
  source: "nointro",
  header_name: "Nintendo - Nintendo Entertainment System",
  version: "20261001",
  sha1: "ab",
  game_count: 3,
  has_parent_clone: 1,
  matches_platform: 1,
  added_at: "",
};

const STATS: Statistics = {
  sources: [
    { id: "nointro", label: "No-Intro (DAT-o-MATIC)", short_label: "No-Intro" },
    { id: "redump", label: "Redump", short_label: "Redump" },
    { id: "tosec", label: "TOSEC", short_label: "TOSEC" },
  ],
  folders: [
    {
      label: "nes",
      platform: "nes",
      platform_short: "NES",
      roms: 10,
      identified: 8,
      coverage: { nointro: { covered: 1, total: 3, dat: DAT } },
      computed_at: "2026-10-20T10:00:00Z",
      stale: true,
    },
    {
      label: "nes-2",
      platform: "nes",
      platform_short: "NES",
      roms: 1000,
      identified: 999,
      coverage: { nointro: { covered: 999, total: 1000, dat: DAT } },
      computed_at: "2026-10-20T09:00:00Z",
      stale: false,
    },
    {
      label: "psx",
      platform: "gb",
      platform_short: "GB",
      roms: 2,
      identified: 2,
      coverage: { redump: { covered: 2, total: 2, dat: { ...DAT, source: "redump" } } },
      computed_at: "2026-10-20T11:00:00Z",
      stale: false,
    },
  ],
  dat_info: [
    {
      id: "nointro",
      label: "No-Intro (DAT-o-MATIC)",
      dats: 1,
      identification_only: false,
      checksums: ["CRC32", "SHA1"],
      categories: ["Demos", "Games"],
      parent_clone: true,
      bios: false,
      serials: false,
      years: false,
      publishers: false,
    },
    {
      id: "tosec",
      label: "TOSEC",
      dats: 0,
      identification_only: false,
      checksums: [],
      categories: [],
      parent_clone: false,
      bios: false,
      serials: false,
      years: false,
      publishers: false,
    },
  ],
  rules: {
    categories: ["Games"],
    excluded_tags: ["Demo", "Proto"],
    tosec_excluded_flags: ["h"],
    tosec_year_pattern: "",
  },
};

const MISSING: Missing = {
  dat: DAT,
  covered: 1,
  total: 3,
  rows: [
    {
      key: "name:Solo",
      name: "Solo",
      versions: 2,
      years: "1987, 1988",
      publishers: "Konami",
      regions: "Japan, USA",
      languages: null,
      serials: null,
      notes: "Zzz Collection",
      marked: false,
      entries: ["Solo (Japan)", "Solo (USA)"],
    },
    {
      key: "name:Tetris",
      name: "Tetris",
      versions: 1,
      years: null,
      publishers: null,
      regions: "USA",
      languages: null,
      serials: null,
      notes: "Unlicensed",
      marked: true,
      entries: ["Tetris (USA) (Unl)"],
    },
  ],
};

test("coverage per DAT source, empty cells, DAT info and the missing games", async () => {
  vi.stubGlobal("fetch", async (url: string) => {
    const body = url.endsWith("/meta")
      ? META
      : url.endsWith("/statistics")
        ? STATS
        : url.endsWith("/statistics/nes/nointro/missing")
          ? MISSING
          : null;
    return new Response(JSON.stringify(body));
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StatisticsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const nes = await screen.findByTestId("statistics-nes");
  // The identified files sit in the Set cell; no Identified column, no views, no filters.
  expect(within(nes).getByText("8 / 10 identified")).toBeInTheDocument();
  expect(screen.queryByTestId("header-identified")).toBeNull();
  expect(screen.queryByTestId("quick-views")).toBeNull();
  expect(screen.queryByTestId("filters-button")).toBeNull();
  // One DATs column: per source a bar, then its name and percentage.
  expect(within(nes).getByTestId("coverage-nes-nointro")).toHaveTextContent("No-Intro33.3%");
  expect(screen.getByTestId("coverage-value-nes-nointro")).not.toHaveClass("text-status-good");
  expect(screen.queryByTestId("header-nointro")).toBeNull();
  // Complete ones in green.
  expect(screen.getByTestId("coverage-bar-nes-nointro").style.transform).toBe(`scaleX(${1 / 3})`);
  expect(screen.getByTestId("coverage-bar-psx-redump")).toHaveClass("bg-status-good");
  // The Set cell's faint background is the identified share; column labels are centred.
  expect(screen.getByTestId("identified-bar-nes").style.transform).toBe("scaleX(0.8)");
  expect(screen.getByTestId("header-dats")).toHaveClass("text-center");
  expect(screen.getByTestId("header-platform")).toHaveClass("text-center");
  expect(within(nes).getByTitle("Nintendo Entertainment System")).toHaveClass("text-center");
  // Kept figures: the oldest computation, and the sets that changed since.
  expect(screen.getByTestId("computed-statistics")).toHaveTextContent(
    "Computed 2026-10-20 09:00 UTC · 1 set changed since",
  );
  expect(within(nes).getByText("· changed")).toBeInTheDocument();
  // Two folders of one platform: a line each. Rounded down, so 999 of 1000 is not 100%.
  const nes2 = screen.getByTestId("coverage-nes-2-nointro");
  expect(nes2).toHaveTextContent("99.9%");
  expect(screen.getByTestId("coverage-value-nes-2-nointro")).not.toHaveClass("text-status-good");
  // No Redump DAT for NES: no bar. TOSEC has no DAT anywhere: shown nowhere.
  expect(within(nes).queryByTestId("coverage-nes-redump")).toBeNull();
  expect(screen.getByTestId("coverage-psx-redump")).toHaveTextContent("Redump100.0%");
  expect(screen.getByTestId("coverage-value-psx-redump")).toHaveClass("text-status-good");
  expect(screen.queryByText("TOSEC")).toBeNull();

  const info = screen.getByTestId("dat-info");
  expect(info).not.toHaveAttribute("open");
  expect(within(info).getByText(/Only games count/)).toBeInTheDocument();
  expect(within(info).getByText(/left-out versions do not count/)).toBeInTheDocument();
  expect(within(info).getByTestId("dat-info-nointro")).toHaveTextContent("Demos, Games");
  expect(within(info).queryByTestId("dat-info-tosec")).toBeNull();

  await userEvent.click(within(nes).getByTestId("coverage-nes-nointro"));
  const dialog = await screen.findByTestId("missing-dialog");
  expect(within(dialog).getByText(/2 of 3 games not in the set/)).toBeInTheDocument();
  const solo = await within(dialog).findByTestId("missing-name:Solo");
  expect(solo).toHaveTextContent("1987, 1988");
  expect(solo).toHaveTextContent("Konami");
  expect(solo).toHaveTextContent("Japan, USA");
  // No version has a language: the column starts hidden.
  expect(within(dialog).queryByText("Languages")).toBeNull();
  expect(within(dialog).getByTestId("missing-name:Tetris")).toHaveTextContent("Unlicensed");

  // Sorting by Obs: unlicensed games first in ascending order, last in descending (even
  // before a note that sorts later in the alphabet).
  const order = () =>
    within(dialog)
      .getAllByTestId(/^missing-name:/)
      .map((row) => row.dataset.testid);
  expect(order()).toEqual(["missing-name:Solo", "missing-name:Tetris"]);
  const obs = within(dialog).getByRole("button", { name: /Obs/ });
  await userEvent.click(obs);
  expect(order()).toEqual(["missing-name:Tetris", "missing-name:Solo"]);
  await userEvent.click(obs);
  expect(order()).toEqual(["missing-name:Solo", "missing-name:Tetris"]);
  // The page's own table keeps its order.
  expect(screen.getAllByTestId(/^statistics-/).map((r) => r.dataset.testid)).toEqual([
    "statistics-nes",
    "statistics-nes-2",
    "statistics-psx",
  ]);
});

test("Refresh recomputes and shows the new figures", async () => {
  const fresh: Statistics = {
    ...STATS,
    folders: STATS.folders.map((f) => ({
      ...f,
      stale: false,
      computed_at: "2026-10-20T12:00:00Z",
    })),
  };
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    const body = url.endsWith("/meta")
      ? META
      : url.endsWith("/statistics/refresh")
        ? fresh
        : url.endsWith("/statistics")
          ? STATS
          : null;
    return new Response(JSON.stringify(body));
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <StatisticsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByTestId("computed-statistics")).toHaveTextContent("changed since");
  await userEvent.click(screen.getByTestId("refresh-statistics"));
  expect(await screen.findByText("Computed 2026-10-20 12:00 UTC")).toBeInTheDocument();
  expect(screen.queryByText("· changed")).toBeNull();
  expect(calls).toContain("POST /api/statistics/refresh");
});
