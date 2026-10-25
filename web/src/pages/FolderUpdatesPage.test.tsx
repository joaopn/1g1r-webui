import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { queryClient } from "@/lib/queries";
import type { UpdateRow } from "@/lib/types";
import { META } from "@/test/fixtures";
import { FolderUpdatesPage } from "./FolderUpdatesPage";

const DETAIL = {
  label: "switch",
  platform: "switch",
  mount: "roms",
  path: "switch",
  location: "/roms/switch",
  on_main_mount: true,
  target: "plain",
  discarded_to: "/roms/discarded/switch/",
  delete_originals: false,
  hidden: false,
  ignored_patterns: [],
  ignored_patterns_default: true,
  ignored_files: [],
  title_ids: true,
  rename_template: "keep",
  rename_templates: ["keep", "dat", "clean"],
  scan: null,
  last_scan: {
    id: 1,
    kind: "identify",
    status: "done",
    started_at: "2026-10-25T10:00:00Z",
    finished_at: "2026-10-25T10:01:00Z",
    message: "5 of 6 files identified by title ID",
    stage: null,
    files_done: null,
    files_total: null,
  },
  summary: { waiting: 0 },
  others: [],
};

const row = (rel_path: string, status: UpdateRow["status"], release: number | null) =>
  ({
    group_key: "tid:0100AAAA00010000",
    game: "Super Game",
    rel_path,
    role: "update",
    notes: release === 2 ? ["content complete"] : [],
    title_id: "0100AAAA00010800",
    version: null,
    release,
    display_version: release === null ? null : `1.0.${release}`,
    size: 7,
    status,
    reason: "",
    operation: status === "older" ? `/roms/discarded/switch/updates/${rel_path}` : null,
    discarded: null,
    // titledb knows a third update.
    latest_version: 196608,
    latest_release: 3,
    latest_date: "2025-03-18",
    newer: status === "newest",
  }) satisfies UpdateRow;

const UPDATES = {
  updates: [
    row("update 2.nsp", "newest", 2),
    row("update 1.nsp", "older", 1),
    {
      ...row("pack.nsp", "dlc", null),
      role: "dlc",
      title_id: "0100AAAA00011001",
      newer: false,
      latest_version: null,
      latest_release: null,
      latest_date: null,
    } satisfies UpdateRow,
  ],
  games: [
    {
      group_key: "tid:0100AAAA00010000",
      game: "Super Game",
      display_version: "1.0.2",
      version: 131072,
      release: 2,
      newer: true,
      latest_release: 3,
      latest_date: "2025-03-18",
      updates: 2,
      dlc: 1,
      to_discard: 1,
      size: 21,
      latest: false,
    },
    {
      group_key: "tid:0100BBBB00010000",
      game: "Lone Game",
      display_version: null,
      version: null,
      release: null,
      newer: false,
      latest_release: null,
      latest_date: null,
      updates: 0,
      dlc: 0,
      to_discard: 0,
      size: 0,
      latest: true,
    },
    {
      group_key: "tid:0100CCCC00010000",
      game: "Behind Game",
      display_version: null,
      version: null,
      release: null,
      newer: true,
      latest_release: 1,
      latest_date: "2024-01-01",
      updates: 0,
      dlc: 0,
      to_discard: 0,
      size: 0,
      latest: false,
    },
  ],
  counts: { total: 2, proposed: 1, unknown: 0, unreadable: 1, dlc: 1, newer: 1 },
};

afterEach(() => {
  vi.unstubAllGlobals();
  queryClient.clear();
});

function stubApi(seen: (url: string, init?: RequestInit) => void) {
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    seen(url, init);
    const body = url.endsWith("/meta")
      ? META
      : url.endsWith("/folders")
        ? []
        : url.includes("/updates")
          ? UPDATES
          : url.endsWith("/run")
            ? null
            : url.endsWith("/keys")
              ? { boot9: false, seeddb: null, prod_keys: null }
              : DETAIL;
    return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  });
}

function renderPage() {
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/folders/switch/updates"]}>
        <Routes>
          <Route path="/folders/:label/updates" element={<FolderUpdatesPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("older updates are proposed, and a Keep click keeps one", async () => {
  const puts: unknown[] = [];
  stubApi((_url, init) => {
    if (init?.method === "PUT") puts.push(JSON.parse(String(init.body)));
  });
  renderPage();
  // Every game is a row: its version, what it holds, what is to do. One with an update to
  // discard is yellow and starts open.
  const game = await screen.findByTestId("updates-game-tid:0100AAAA00010000");
  // Its version, titledb's newer one, then what it holds, all in the game's cell.
  expect(within(game).getAllByTitle(/titledb knows a newer update/)[0]).toHaveTextContent(
    "Super Game (update 2 v1.0.2, update 3 latest)2 updates · 1 DLC",
  );
  expect(game).toHaveTextContent("1 older → discard");
  expect(within(game).getByText("Super Game")).toHaveClass("text-status-warn");
  expect(screen.getByTestId("update-update 2.nsp")).toBeInTheDocument();
  await userEvent.click(within(game).getByRole("button", { name: "Super Game: collapse" }));
  expect(screen.queryByTestId("update-update 2.nsp")).toBeNull();
  await userEvent.click(within(game).getByRole("button", { name: "Super Game: show" }));
  // On titledb's newest update: green, nothing to open. Behind it: blue.
  const lone = screen.getByTestId("updates-game-tid:0100BBBB00010000");
  expect(lone).toHaveTextContent("no update");
  expect(within(lone).getByText("Lone Game")).toHaveClass("text-status-good");
  expect(within(lone).queryByRole("button")).toBeNull();
  const behind = screen.getByTestId("updates-game-tid:0100CCCC00010000");
  expect(within(behind).getByText("Behind Game")).toHaveClass("text-status-info");
  expect(behind).toHaveTextContent("newer released");
  expect(screen.getByText(/3 of 3 games/)).toBeInTheDocument();

  expect(screen.getByTestId("update-update 2.nsp")).toHaveTextContent("newest, kept");
  expect(screen.getByTestId("update-update 2.nsp")).toHaveTextContent("1.0.2");
  expect(screen.getByText("games with a newer update")).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /Newer released/ })).toBeInTheDocument();
  // DLC: listed, "DLC" in grey as its version, kept, no Keep button.
  const pack = screen.getByTestId("update-pack.nsp");
  expect(pack).toHaveTextContent("DLC, kept");
  expect(within(pack).getAllByText("DLC")[0]).toHaveClass("text-muted-foreground");
  expect(within(pack).queryByRole("button", { name: /Keep/ })).toBeNull();
  // prod.keys suggested for the unreadable update.
  expect(screen.getByTestId("unreadable-updates")).toHaveTextContent(
    "1 update has no readable version",
  );
  // Columns: Version (shown) and Size before Status by default; Update and Latest hidden.
  const headers = within(screen.getByRole("region", { name: "Updates & DLC" }))
    .getAllByTestId(/^header-/)
    .map((h) => h.textContent);
  expect(headers.join("|")).toMatch(/Game.*File name.*Version.*Size.*Status/);
  expect(headers.join("|")).not.toMatch(/Latest|Update\b/);
  expect(await screen.findByText("· not added")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add" })).toBeEnabled();
  const older = screen.getByTestId("update-update 1.nsp");
  expect(older).toHaveTextContent("older → discard");
  expect(screen.getByRole("button", { name: "Discard (1 file)" })).toBeEnabled();
  expect(screen.getByRole("region", { name: "Discard old updates" })).toHaveTextContent(
    "1 file older than their game's newest update",
  );
  await userEvent.click(within(older).getByRole("button", { name: "Keep update 1.nsp" }));
  await vi.waitFor(() => expect(puts).toEqual([{ rel_paths: ["update 1.nsp"], keep: true }]));
});

test("a quick scan from the tab picks up an update added by hand", async () => {
  const posts: string[] = [];
  stubApi((url, init) => {
    if (init?.method === "POST") posts.push(url);
  });
  renderPage();
  const box = await screen.findByRole("region", { name: "Discard old updates" });
  expect(box).toHaveTextContent("A quick scan reads only new files.");
  expect(within(box).queryByRole("button", { name: /Full scan/ })).toBeNull();
  await userEvent.click(within(box).getByRole("button", { name: /Quick scan/ }));
  await vi.waitFor(() => expect(posts).toEqual(["/api/folders/switch/scan"]));
});
