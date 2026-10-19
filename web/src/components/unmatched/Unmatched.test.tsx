import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { GamesTable } from "@/components/games/GamesTable";
import { queryClient } from "@/lib/queries";
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
];

const PREVIEW = {
  token: "t",
  files: [{ rel_path: FILES[0].rel_path, size: FILES[0].size, destination: null }],
  irreversible: 1,
  bytes: FILES[0].size,
  problems: [],
  busy: null,
};

/** The Matching page's table, with its unmatched files as rows. */
function Table({ lookupsOn }: { lookupsOn: boolean }) {
  const actions = useUnmatchedActions("nes", META);
  return (
    <>
      <GamesTable
        label="nes"
        games={GAMES}
        meta={META}
        onKeep={vi.fn()}
        onLeave={vi.fn()}
        unmatched={{
          files: FILES,
          busy: false,
          onAssign: actions.assign,
          onMove: actions.move,
          tools: (files) => (
            <UnmatchedTools
              label="nes"
              files={files}
              lookupsOn={lookupsOn}
              scanning={false}
              onMove={actions.move}
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
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = url.endsWith("/unmatched/preview")
      ? PREVIEW
      : url.endsWith("/unmatched")
        ? FILES
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
  expect(within(bar).getByText("Unmatched")).toHaveTextContent(/^Unmatched1$/);
  // "One version" is for games: a file nothing identified is not one.
  expect(within(bar).getByText("One version")).toHaveTextContent(`One version${single}`);
  expect(screen.getByText("Doraemon (Japan) (Rev 1)")).toBeInTheDocument();
  expect(screen.queryByText("Look up again")).not.toBeInTheDocument();

  await userEvent.click(within(bar).getByText("Unmatched"));
  expect(screen.queryByText("Contra")).not.toBeInTheDocument();
  expect(screen.getByText("Doraemon (Japan) (Rev 1)")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Look up again/ })).toBeInTheDocument();
});

test("an unmatched row shows what Hasheous said, and a suggestion assigns it", async () => {
  const calls = renderSection(true, UNMATCHED_VIEW);
  const suggestion = await screen.findByRole("button", { name: /^Doraemon \(Japan\) .*%$/ });
  expect(screen.getByText("Hasheous: not found online")).toBeInTheDocument();
  expect(screen.getByText(/84%/)).toBeInTheDocument();
  await userEvent.click(suggestion);
  const put = calls.find((c) => c.url.endsWith("/assign"));
  expect(JSON.parse(String(put?.init?.body))).toEqual({
    rel_path: "Doraemon (Japan) (Rev 1).zip",
    game_name: "Doraemon (Japan)",
  });
});

test("with lookups off it links to the settings instead of offering a retry", async () => {
  renderSection(false, UNMATCHED_VIEW);
  expect(await screen.findByText("Online lookups are off")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Look up again/ })).not.toBeInTheDocument();
});

test("the row is collapsible to the file alone", async () => {
  renderSection(true, UNMATCHED_VIEW);
  expect(screen.getByText("Hasheous: not found online")).toBeInTheDocument();
  await userEvent.click(
    screen.getByRole("button", { name: "Doraemon (Japan) (Rev 1): collapse the details" }),
  );
  expect(screen.queryByText("Hasheous: not found online")).not.toBeInTheDocument();
});

test("moving every file shown reviews them all", async () => {
  const calls = renderSection(true, UNMATCHED_VIEW);
  await userEvent.click(screen.getByRole("button", { name: /Move 1 file to discarded/ }));
  await screen.findByRole("button", { name: "Move 1 file" });
  const preview = calls.find((c) => c.url.endsWith("/unmatched/preview"));
  expect(JSON.parse(String(preview?.init?.body))).toMatchObject({
    rel_paths: ["Doraemon (Japan) (Rev 1).zip"],
    delete: false,
  });
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
