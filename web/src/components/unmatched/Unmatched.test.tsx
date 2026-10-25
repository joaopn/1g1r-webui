import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { GamesTable } from "@/components/games/GamesTable";
import { queryClient, useUnmatched } from "@/lib/queries";
import type { UnmatchedFile } from "@/lib/types";
import { GAMES, META } from "@/test/fixtures";
import { UnmatchedTools, useUnmatchedActions } from "./Unmatched";

const FILES: UnmatchedFile[] = [
  {
    rel_path: "Doraemon (Japan) (Rev 1).zip",
    size: 163856,
    hash: { crc32: "83348047", sha1: "71322777250ea6573554ea04538f1b2ae9b76b83" },
    hasheous: { status: "not found", detail: "" },
    suggestions: [{ game_name: "Doraemon (Japan)", score: 0.84 }],
  },
  {
    rel_path: "Aa Harimanada.zip",
    size: 131088,
    hash: null,
    hasheous: { status: "not found", detail: "" },
    suggestions: [{ game_name: "Aa Harimanada (Japan)", score: 0.9 }],
  },
  {
    rel_path: "mystery.zip",
    size: 4096,
    hash: null,
    hasheous: { status: "not found", detail: "" },
    suggestions: [],
  },
];

/** The review of the files asked about. */
function preview(relPaths: string[]) {
  const files = FILES.filter((f) => relPaths.includes(f.rel_path));
  return {
    token: "t",
    files: files.map((f) => ({ rel_path: f.rel_path, size: f.size, destination: null })),
    irreversible: files.length,
    bytes: files.reduce((n, f) => n + f.size, 0),
    problems: [],
    busy: null,
  };
}

/** The Matching page's table, with its unmatched files as rows. */
function Table({ lookupsOn }: { lookupsOn: boolean }) {
  const actions = useUnmatchedActions("nes", META);
  const files = useUnmatched("nes").data ?? FILES;
  return (
    <>
      <GamesTable
        label="nes"
        games={GAMES}
        meta={META}
        onKeep={vi.fn()}
        onLeave={vi.fn()}
        unmatched={{
          files,
          busy: false,
          onAssign: actions.assign,
          onMove: actions.move,
          tools: (files, selected, clear) => (
            <UnmatchedTools
              label="nes"
              files={files}
              selected={selected}
              lookupsOn={lookupsOn}
              scanning={false}
              onMove={actions.move}
              onMatchFirst={actions.matchFirst}
              onClearSelection={clear}
            />
          ),
        }}
      />
      {actions.dialog}
    </>
  );
}

function renderSection(lookupsOn: boolean, path = "/folders/nes/matching") {
  const calls: { url: string; init?: RequestInit }[] = [];
  let files = FILES;
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.endsWith("/assign-many")) {
      const done = new Set(
        JSON.parse(String(init?.body)).assignments.map((a: { rel_path: string }) => a.rel_path),
      );
      files = files.filter((f) => !done.has(f.rel_path));
    }
    const body = url.endsWith("/unmatched/preview")
      ? preview(JSON.parse(String(init?.body)).rel_paths)
      : url.endsWith("/unmatched")
        ? files
        : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <Table lookupsOn={lookupsOn} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

const UNMATCHED_VIEW = "/folders/nes/matching?view=unmatched";

beforeEach(() => window.localStorage.clear());

test("unmatched files are rows of the table, with a quick view of their own", async () => {
  renderSection(true);
  const bar = screen.getByTestId("quick-views");
  const single = GAMES.filter((g) => g.versions.length === 1).length;
  expect(within(bar).getByText("Unmatched")).toHaveTextContent(/^Unmatched3$/);
  // "One version" is for games: a file nothing identified is not one.
  expect(within(bar).getByText("One version")).toHaveTextContent(`One version${single}`);
  expect(screen.getByText("Doraemon (Japan) (Rev 1)")).toBeInTheDocument();
  expect(screen.queryByText("Rematch unmatched")).not.toBeInTheDocument();

  await userEvent.click(within(bar).getByText("Unmatched"));
  expect(screen.queryByText("Contra")).not.toBeInTheDocument();
  expect(screen.getByText("Doraemon (Japan) (Rev 1)")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Rematch unmatched/ })).toBeInTheDocument();
});

test("the Unmatched view shows each file's 1st match, rows closed", async () => {
  renderSection(true, UNMATCHED_VIEW);
  expect(screen.getByText("1st match")).toBeInTheDocument();
  expect(screen.getByText("Doraemon (Japan)")).toBeInTheDocument();
  expect(screen.getByText("84%")).toBeInTheDocument();
  expect(screen.getByText("no close name")).toBeInTheDocument();
  // Closed: the details (and their suggestion buttons) wait for the chevron.
  expect(screen.queryByText("Hasheous: not found online")).not.toBeInTheDocument();
});

test("the chevron opens a row; a suggestion there assigns it", async () => {
  const calls = renderSection(true, UNMATCHED_VIEW);
  await userEvent.click(
    screen.getByRole("button", { name: "Doraemon (Japan) (Rev 1): show the details" }),
  );
  expect(screen.getByText("Hasheous: not found online")).toBeInTheDocument();
  // Opening is not selecting.
  expect(screen.getByRole("button", { name: "Select Doraemon (Japan) (Rev 1)" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  const suggestion = await screen.findByRole("button", { name: /^Doraemon \(Japan\) .*%$/ });
  await userEvent.click(suggestion);
  const put = calls.find((c) => c.url.endsWith("/assign-many"));
  expect(JSON.parse(String(put?.init?.body))).toEqual({
    assignments: [{ rel_path: "Doraemon (Japan) (Rev 1).zip", game_name: "Doraemon (Japan)" }],
  });
  // The row leaves the table without waiting for the refetch.
  expect(screen.queryByText("Doraemon (Japan) (Rev 1)")).not.toBeInTheDocument();
});

test("a click on the file name copies it and selects nothing", async () => {
  const user = userEvent.setup();
  renderSection(true, UNMATCHED_VIEW);
  await user.click(screen.getByRole("button", { name: 'Copy "Doraemon (Japan) (Rev 1)"' }));
  expect(await navigator.clipboard.readText()).toBe("Doraemon (Japan) (Rev 1)");
  expect(screen.getByRole("button", { name: "Select Doraemon (Japan) (Rev 1)" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  // The rest of the row still selects it.
  await user.click(screen.getByRole("button", { name: "Select Doraemon (Japan) (Rev 1)" }));
  expect(screen.getByText(/1 file selected/)).toBeInTheDocument();
});

test("match to 1st takes the selected rows only, and skips rows without a match", async () => {
  const calls = renderSection(true, UNMATCHED_VIEW);
  const match = screen.getByRole("button", { name: /to 1st/ });
  expect(match).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Select Doraemon (Japan) (Rev 1)" }));
  await userEvent.click(screen.getByRole("button", { name: "Select mystery" }));
  expect(screen.getByText(/2 files selected/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Move 2 files to discarded/ })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Match 1 file to 1st/ }));
  const put = calls.find((c) => c.url.endsWith("/assign-many"));
  expect(JSON.parse(String(put?.init?.body))).toEqual({
    assignments: [{ rel_path: "Doraemon (Japan) (Rev 1).zip", game_name: "Doraemon (Japan)" }],
  });
  expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
});

test("shift-click selects a range", async () => {
  renderSection(true, UNMATCHED_VIEW);
  const rows = screen
    .getAllByRole("button", { name: /^Select / })
    .map((row) => row.getAttribute("aria-label"));
  await userEvent.click(screen.getByRole("button", { name: rows[0] ?? "" }));
  const user = userEvent.setup();
  await user.keyboard("{Shift>}");
  await user.click(screen.getByRole("button", { name: rows[rows.length - 1] ?? "" }));
  await user.keyboard("{/Shift}");
  expect(screen.getByText(/3 files selected/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Match 2 files to 1st/ })).toBeEnabled();
});

test("with lookups off it still rematches against the DATs and links to the settings", async () => {
  const calls = renderSection(false, UNMATCHED_VIEW);
  expect(await screen.findByText("Online lookups are off")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Rematch unmatched/ }));
  await waitFor(() => expect(calls.some((c) => c.url.includes("/scan?rematch=true"))).toBe(true));
});

test("moving every file shown reviews them all", async () => {
  const calls = renderSection(true, UNMATCHED_VIEW);
  await userEvent.click(screen.getByRole("button", { name: /Move 3 files to discarded/ }));
  await screen.findByRole("button", { name: "Move 3 files" });
  const preview = calls.find((c) => c.url.endsWith("/unmatched/preview"));
  expect(JSON.parse(String(preview?.init?.body)).rel_paths).toHaveLength(FILES.length);
});

test("deleting a file asks for the folder label first", async () => {
  const calls = renderSection(false);
  await userEvent.click(
    await screen.findByRole("button", { name: "Delete Doraemon (Japan) (Rev 1).zip" }),
  );
  const run = await screen.findByRole("button", { name: "Delete 1 file" });
  expect(run).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Folder label"), "nes");
  await userEvent.click(run);
  const sent = calls.find((c) => c.url === "/api/folders/nes/unmatched" && c.init?.body);
  expect(JSON.parse(String(sent?.init?.body))).toEqual({
    rel_paths: ["Doraemon (Japan) (Rev 1).zip"],
    delete: true,
    token: "t",
    confirm: "nes",
  });
});
