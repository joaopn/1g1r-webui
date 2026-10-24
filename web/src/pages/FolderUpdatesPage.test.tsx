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
  scan: null,
  others: [],
};

const row = (rel_path: string, status: UpdateRow["status"], release: number | null) =>
  ({
    group_key: "tid:0100AAAA00010000",
    game: "Super Game",
    rel_path,
    title_id: "0100AAAA00010800",
    version: null,
    release,
    display_version: release === null ? null : `1.0.${release}`,
    size: 7,
    status,
    reason: "",
    operation: status === "older" ? `/roms/discarded/switch/updates/${rel_path}` : null,
    discarded: null,
  }) satisfies UpdateRow;

const UPDATES = {
  updates: [row("update 2.nsp", "newest", 2), row("update 1.nsp", "older", 1)],
  counts: { total: 2, proposed: 1, unknown: 0 },
};

afterEach(() => {
  vi.unstubAllGlobals();
  queryClient.clear();
});

test("older updates are proposed, and a Keep click keeps one", async () => {
  const puts: unknown[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") puts.push(JSON.parse(String(init.body)));
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
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/folders/switch/updates"]}>
        <Routes>
          <Route path="/folders/:label/updates" element={<FolderUpdatesPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByTestId("update-update 2.nsp")).toHaveTextContent("newest, kept");
  expect(screen.getByTestId("update-update 2.nsp")).toHaveTextContent("1.0.2");
  expect(await screen.findByText("· not added")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add" })).toBeEnabled();
  const older = screen.getByTestId("update-update 1.nsp");
  expect(older).toHaveTextContent("older → discard");
  expect(screen.getByRole("button", { name: /Move 1 file to discarded/ })).toBeEnabled();
  await userEvent.click(within(older).getByRole("button", { name: "Keep update 1.nsp" }));
  await vi.waitFor(() => expect(puts).toEqual([{ rel_paths: ["update 1.nsp"], keep: true }]));
});
