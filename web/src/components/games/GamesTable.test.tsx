import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { Game } from "@/lib/types";
import { GAMES, META } from "@/test/fixtures";
import { COLUMNS_KEY, flagTone, methodLabel } from "./columns";
import { GamesTable } from "./GamesTable";

function renderTable(onKeep = vi.fn(), onLeave = vi.fn()) {
  render(
    <MemoryRouter>
      <GamesTable label="nes" games={GAMES} meta={META} onKeep={onKeep} onLeave={onLeave} />
    </MemoryRouter>,
  );
  return { onKeep, onLeave };
}

const gameNames = () =>
  screen
    .getAllByRole("button", { name: /: (collapse|show)/ })
    .map((el) => el.getAttribute("aria-label")?.split(":")[0]);

beforeEach(() => window.localStorage.clear());

test("multi-version games start expanded and collapse on click", async () => {
  renderTable();
  expect(screen.getByTestId("version-Contra (Japan).zip")).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Contra: collapse to the kept version" }),
  );
  expect(screen.queryByTestId("version-Contra (Japan).zip")).not.toBeInTheDocument();
  // Collapsed, the game's row shows the kept version.
  expect(screen.getByTitle("Contra (USA).zip")).toBeInTheDocument();
});

test("clicking a version keeps it; clicking the kept one does nothing unless it is your pick", async () => {
  const { onKeep } = renderTable();
  await userEvent.click(screen.getByTestId("version-Gradius (USA) (Rev 1).zip"));
  expect(onKeep).toHaveBeenCalledWith(GAMES[1], "Gradius (USA) (Rev 1).zip");
  onKeep.mockClear();
  await userEvent.click(screen.getByTestId("version-Contra (USA).zip"));
  expect(onKeep).not.toHaveBeenCalled();
});

test("leave alone is a button on the game row", async () => {
  const { onLeave } = renderTable();
  const contra = screen.getByRole("button", {
    name: "Contra: collapse to the kept version",
  }).parentElement;
  await userEvent.click(within(contra as HTMLElement).getByRole("button", { name: /leave alone/ }));
  expect(onLeave).toHaveBeenCalledWith(GAMES[0], true);
});

test("sorting by status puts undecided games first, and reverses", async () => {
  renderTable();
  await userEvent.click(screen.getByTestId("sort-status"));
  expect(gameNames()[0]).toBe("Gradius");
  await userEvent.click(screen.getByTestId("sort-status"));
  expect(gameNames().at(-1)).toBe("Gradius");
});

test("the column chooser hides a column and remembers it", async () => {
  renderTable();
  expect(screen.getByTestId("header-region")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("columns-button"));
  await userEvent.click(screen.getByTestId("column-region"));
  expect(screen.queryByTestId("header-region")).not.toBeInTheDocument();
  expect(JSON.parse(window.localStorage.getItem(COLUMNS_KEY) ?? "[]")).not.toContain("region");
});

test("a column is resized with the keyboard and reset by double-click", async () => {
  renderTable();
  const handle = screen.getByTestId("resize-file");
  const start = Number(handle.getAttribute("aria-valuenow"));
  handle.focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(Number(screen.getByTestId("resize-file").getAttribute("aria-valuenow"))).toBeCloseTo(
    start + META.ui.resize_step_rem,
  );
  await userEvent.dblClick(screen.getByTestId("resize-file"));
  expect(Number(screen.getByTestId("resize-file").getAttribute("aria-valuenow"))).toBe(start);
});

test("search and the status filter narrow the list", async () => {
  renderTable();
  await userEvent.type(screen.getByLabelText("Search games"), "contra");
  expect(gameNames()).toEqual(["Contra"]);
  await userEvent.clear(screen.getByLabelText("Search games"));
  await userEvent.click(screen.getByTestId("filters-button"));
  await userEvent.click(screen.getByRole("checkbox", { name: /undecided/ }));
  expect(gameNames()).toEqual(["Gradius"]);
});

test("the quick-view bar shows one-version or several-version games, with counts", async () => {
  renderTable();
  const bar = screen.getByTestId("quick-views");
  expect(within(bar).getByRole("radio", { name: /All/ })).toBeChecked();
  // The undecided share of Several versions is counted beside it; other views have none.
  const chip = (name: RegExp) => within(bar).getByRole("radio", { name }).closest("label");
  expect(chip(/Several versions/)).toHaveTextContent(/^Several versions2 \(1 undecided\)$/);
  expect(chip(/One version/)).toHaveTextContent(/^One version1$/);
  await userEvent.click(within(bar).getByRole("radio", { name: /Several versions/ }));
  // Sorted by status by default: the undecided game first.
  expect(gameNames()).toEqual(["Gradius", "Contra"]);
  expect(screen.queryByText("Arkanoid")).not.toBeInTheDocument();
  await userEvent.click(within(bar).getByRole("radio", { name: /One version/ }));
  expect(screen.getByText("Arkanoid")).toBeInTheDocument();
  expect(screen.queryByText("Contra")).not.toBeInTheDocument();
});

test("a version you assigned by hand can be unassigned from its match cell", async () => {
  const onUnassign = vi.fn();
  const onKeep = vi.fn();
  const games = GAMES.map((g) =>
    g.name === "Arkanoid"
      ? { ...g, versions: g.versions.map((v) => ({ ...v, method: "manual" })) }
      : g,
  );
  render(
    <MemoryRouter>
      <GamesTable
        label="nes"
        games={games}
        meta={META}
        onKeep={onKeep}
        onLeave={vi.fn()}
        onUnassign={onUnassign}
      />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Unassign Arkanoid (Japan).zip" }));
  expect(onUnassign).toHaveBeenCalledWith(expect.objectContaining({ method: "manual" }));
  expect(onKeep).not.toHaveBeenCalled();
});

test("a game with proposed moves has an apply button; a discarded version restores", async () => {
  const onApplyGame = vi.fn();
  const onRestore = vi.fn();
  const applied: Game = {
    ...GAMES[0],
    status: "applied",
    reason: "the other versions are in discarded/",
    versions: GAMES[0].versions.map((v) =>
      v.operation ? { ...v, operation: null, discarded: 7 } : v,
    ),
  };
  render(
    <MemoryRouter>
      <GamesTable
        label="nes"
        games={[GAMES[0], { ...applied, key: "name:Contra2", name: "Contra 2" }]}
        meta={META}
        onKeep={vi.fn()}
        onLeave={vi.fn()}
        onApplyGame={onApplyGame}
        onRestore={onRestore}
      />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Apply Contra" }));
  expect(onApplyGame).toHaveBeenCalledWith(GAMES[0]);
  expect(screen.queryByRole("button", { name: "Restore Contra" })).not.toBeInTheDocument();

  const versions = screen.getAllByTestId("version-Contra (Japan).zip");
  const gone = versions[1];
  expect(gone).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(within(gone).getByRole("button", { name: /Restore Contra \(Japan\)/ }));
  expect(onRestore).toHaveBeenCalledWith({ version: expect.objectContaining({ discarded: 7 }) });
  await userEvent.click(screen.getByRole("button", { name: "Restore Contra 2" }));
  expect(onRestore).toHaveBeenLastCalledWith({
    game: expect.objectContaining({ name: "Contra 2" }),
  });
});

test("an identical copy shows where it goes", async () => {
  const games = GAMES.map((g, i) =>
    i === 0
      ? {
          ...g,
          versions: g.versions.map((v, j) =>
            j === 0
              ? {
                  ...v,
                  method: "duplicate",
                  identical: [g.versions[1].rel_path],
                  operation: "/roms/discarded/nes/duplicates/x.zip",
                  discard_reason: "duplicates" as const,
                }
              : v,
          ),
        }
      : g,
  );
  render(
    <MemoryRouter>
      <GamesTable label="nes" games={games} meta={META} onKeep={vi.fn()} onLeave={vi.fn()} />
    </MemoryRouter>,
  );
  expect(await screen.findByText("→ duplicates")).toBeInTheDocument();
  expect(
    screen.getByTitle(/^byte-identical .* · identical to Contra \(USA\)\.zip$/),
  ).toBeInTheDocument();
});

test("Matched by names the DAT that identified the version", () => {
  const version = {
    ...GAMES[0].versions[0],
    method: "dat-headerless",
    dat: {
      source: "nointro",
      label: "No-Intro",
      source_label: "No-Intro (DAT-o-MATIC)",
      version: "20261018",
      header_name: "Nintendo - Nintendo Entertainment System (Headered)",
    },
  };
  expect(methodLabel(version)).toEqual({
    short: "No-Intro, no header",
    long:
      "checksum match in the DAT after removing a copier header · No-Intro (DAT-o-MATIC): " +
      "Nintendo - Nintendo Entertainment System (Headered) (20261018)",
  });
  expect(methodLabel({ ...version, method: "hasheous", dat: null }).short).toBe("Hasheous");
  // A title ID named by a titledb file: both.
  const titledb = {
    source: "titledb:US.en",
    label: "titledb US.en",
    source_label: "titledb US.en",
    version: "2026-10-24",
    header_name: "titledb US.en",
  };
  const named = methodLabel({ ...version, method: "title-id", dat: titledb });
  expect(named.short).toBe("title ID · titledb US.en");
  expect(named.long).toMatch(/ · titledb US\.en \(2026-10-24\)$/);
});

test("content checked against titledb is coloured: complete good, incomplete a warning", () => {
  expect(flagTone("content complete")).toContain("text-status-good");
  expect(flagTone("content incomplete: 1 missing")).toContain("text-status-warn");
  expect(flagTone("encrypted")).toBe("");
});

test("a file waiting for its conversion is its own row, linking to the Conversion tab", async () => {
  render(
    <MemoryRouter>
      <GamesTable
        label="nes"
        games={GAMES}
        meta={META}
        onKeep={vi.fn()}
        onLeave={vi.fn()}
        convertFirst={[{ rel_path: "loose/Wait (USA).nes", size: 40, kind: "rom" }]}
      />
    </MemoryRouter>,
  );
  expect(screen.getByText(/1 file to convert first/)).toBeInTheDocument();
  const link = screen.getByRole("link", { name: "Convert loose/Wait (USA).nes first" });
  expect(link).toHaveAttribute("href", "/folders/nes/conversion");
  // Not a version: nothing is kept, and it is neither a one-version game nor unmatched.
  expect(screen.queryByRole("img", { name: "kept" })).toBeNull();
  const bar = screen.getByTestId("quick-views");
  expect(within(bar).getByText("Convert first").parentElement).toHaveTextContent("1");
  await userEvent.click(within(bar).getByRole("radio", { name: /Convert first/ }));
  expect(screen.getByText("Wait (USA)")).toBeInTheDocument();
  expect(screen.queryByText("Contra")).not.toBeInTheDocument();
  await userEvent.click(within(bar).getByRole("radio", { name: /One version/ }));
  expect(screen.queryByText("Wait (USA)")).not.toBeInTheDocument();
});

test("Several versions starts sorted by status, undecided first", () => {
  render(
    <MemoryRouter initialEntries={["/?view=several"]}>
      <GamesTable label="nes" games={GAMES} meta={META} onKeep={vi.fn()} onLeave={vi.fn()} />
    </MemoryRouter>,
  );
  expect(gameNames()).toEqual(["Gradius", "Contra"]);
});

test("a game's versions are listed by file name, revisions after the first release", () => {
  const [, gradius] = GAMES;
  const base = gradius.versions[0];
  const named = (rel_path: string) => ({ ...base, rel_path });
  const game: Game = {
    ...gradius,
    // The API lists versions in ranking order.
    versions: [
      named("Gradius (USA) (Rev 10).zip"),
      named("Gradius (USA) (Rev 2).zip"),
      named("Gradius (USA).zip"),
    ],
  };
  render(
    <MemoryRouter>
      <GamesTable label="nes" games={[game]} meta={META} onKeep={vi.fn()} onLeave={vi.fn()} />
    </MemoryRouter>,
  );
  const rows = screen
    .getAllByTestId(/^version-/)
    .map((el) => el.getAttribute("data-testid")?.replace("version-", ""));
  expect(rows).toEqual([
    "Gradius (USA).zip",
    "Gradius (USA) (Rev 2).zip",
    "Gradius (USA) (Rev 10).zip",
  ]);
});

test("a title-ID game counts its updates and DLC, linking to the Updates & DLC tab", () => {
  const game: Game = { ...GAMES[0], extras: { updates: 2, dlc: 1 } };
  render(
    <MemoryRouter>
      <GamesTable label="switch" games={[game]} meta={META} onKeep={vi.fn()} onLeave={vi.fn()} />
    </MemoryRouter>,
  );
  const link = screen.getByRole("link", { name: "+2 updates · 1 DLC" });
  expect(link).toHaveAttribute("href", "/folders/switch/updates");
});
