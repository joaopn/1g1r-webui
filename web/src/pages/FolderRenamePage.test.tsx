import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { queryClient } from "@/lib/queries";
import type { Renames } from "@/lib/types";
import { META } from "@/test/fixtures";
import { FolderRenamePage } from "./FolderRenamePage";

const DETAIL = {
  label: "nes",
  platform: "nes",
  mount: "roms",
  path: "nes",
  location: "/roms/nes",
  on_main_mount: true,
  target: "zip",
  discarded_to: "/roms/discarded/nes/",
  delete_originals: false,
  hidden: false,
  ignored_patterns: [],
  ignored_patterns_default: true,
  ignored_files: [],
  title_ids: false,
  rename_template: "dat",
  rename_templates: ["keep", "dat", "clean"],
  scan: null,
  others: [],
};

const row = (rel_path: string, extra: Partial<Renames["rows"][number]>) => ({
  rel_path,
  size: 4,
  game: "Contra (USA)",
  method: "dat-checksum",
  status: "skipped" as const,
  new_path: null,
  reason: "",
  original: null,
  ...extra,
});

const RENAMES: Renames = {
  template: "dat",
  rows: [
    row("contra.zip", { status: "rename", new_path: "Contra (USA).zip" }),
    row("Gradius (USA).zip", { game: "Gradius (USA)", status: "named", original: "g.zip" }),
    row("stray.zip", { game: null, method: null, reason: "not identified" }),
  ],
  counts: { files: 3, proposed: 1, named: 1, skipped: 1, renamed: 1 },
  waiting: 0,
};

afterEach(() => {
  vi.unstubAllGlobals();
  queryClient.clear();
});

function renderPage(renames: Renames = RENAMES) {
  const posts: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "POST" || init?.method === "PUT")
      posts.push({ url, body: JSON.parse(String(init.body)) });
    const body = url.endsWith("/meta")
      ? META
      : url.endsWith("/folders")
        ? []
        : url.endsWith("/preview")
          ? {
              token: "t",
              files: [
                { rel_path: "contra.zip", size: 4, destination: "/roms/nes/Contra (USA).zip" },
              ],
              irreversible: 0,
              bytes: 4,
              problems: [],
              busy: null,
            }
          : url.endsWith("/rename")
            ? renames
            : url.endsWith("/run")
              ? null
              : DETAIL;
    return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/folders/nes/rename"]}>
        <Routes>
          <Route path="/folders/:label/rename" element={<FolderRenamePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return posts;
}

test("proposed names are listed, renamed once reviewed, and a renamed file can be reverted", async () => {
  const posts = renderPage();
  const contra = await screen.findByTestId("rename-contra.zip");
  expect(contra).toHaveTextContent("Contra (USA).zip");
  expect(contra).toHaveTextContent("to rename");
  expect(screen.getByTestId("rename-stray.zip")).toHaveTextContent("not identified");
  const gradius = screen.getByTestId("rename-Gradius (USA).zip");
  expect(gradius).toHaveTextContent("renamed");
  expect(gradius).toHaveTextContent("g.zip");
  expect(screen.getByTestId("rename-template")).toHaveTextContent("DAT name");

  await userEvent.click(screen.getByRole("button", { name: "Rename (1 file)" }));
  const dialog = await screen.findByRole("dialog");
  // The new name, not "discarded"; igir's rehash said.
  expect(await within(dialog).findByTestId("guarded-files")).toHaveTextContent(
    "contra.zipContra (USA).zip",
  );
  expect(dialog).toHaveTextContent("igir reads renamed files again");
  await userEvent.click(within(dialog).getByRole("button", { name: "Rename 1 file" }));
  expect(posts.some((p) => p.url.endsWith("/folders/nes/rename"))).toBe(true);

  await userEvent.click(
    screen.getByRole("button", { name: "Give Gradius (USA).zip back its original name" }),
  );
  await screen.findByRole("dialog");
  const reverts = posts.filter((p) => p.url.endsWith("/rename/revert/preview"));
  expect(reverts.at(-1)?.body).toEqual({ rel_paths: ["Gradius (USA).zip"] });
});

test("renaming waits while files are to convert; reverting does not", async () => {
  renderPage({ ...RENAMES, waiting: 2 });
  expect(await screen.findByTestId("rename-waiting")).toHaveTextContent(
    "Convert or discard first: 2 files",
  );
  expect(screen.getByRole("button", { name: "Rename (1 file)" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Revert (1 file)" })).toBeEnabled();
});

test("the set's naming template is picked on the tab too", async () => {
  const posts = renderPage();
  const select = await screen.findByRole("combobox", { name: "Naming template" });
  expect(select).toHaveValue("dat");
  await userEvent.selectOptions(select, "clean");
  expect(posts.find((p) => p.url.endsWith("/folders/nes/rename-template"))?.body).toEqual({
    template: "clean",
  });
});
