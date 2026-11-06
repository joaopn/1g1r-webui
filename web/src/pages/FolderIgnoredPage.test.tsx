import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { queryClient } from "@/lib/queries";
import { META } from "@/test/fixtures";
import { FolderIgnoredPage } from "./FolderIgnoredPage";

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
  auto_check: false,
  ignored_patterns: ["*.txt", "*.png"],
  ignored_patterns_default: false,
  ignored_files: ["sub/scan.jpg"],
  scan: null,
  others: [
    { rel_path: "notes.txt", size: 3, kind: "ignored", ignored_by: "*.txt" },
    { rel_path: "sub/scan.jpg", size: 5, kind: "ignored", ignored_by: "file" },
    { rel_path: "cover.bmp", size: 5, kind: "other", ignored_by: null },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
  queryClient.clear();
});

function renderPage() {
  const puts: unknown[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "PUT") puts.push(JSON.parse(String(init.body)));
    const body = url.endsWith("/meta")
      ? META
      : url.endsWith("/folders")
        ? []
        : init?.method === "PUT"
          ? { ...DETAIL, checking: true }
          : DETAIL;
    return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/folders/nes/ignored"]}>
        <Routes>
          <Route path="/folders/:label/ignored" element={<FolderIgnoredPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return puts;
}

test("the set's ignore list is edited on its Ignored tab, beside the files it leaves out", async () => {
  const puts = renderPage();
  expect(await screen.findByText("Ignored files (2)")).toBeInTheDocument();
  expect(screen.getByTestId("ignored-notes.txt")).toHaveTextContent("*.txt");
  expect(screen.getByTestId("ignored-sub/scan.jpg")).toHaveTextContent("this file");
  expect(screen.queryByTestId("ignored-cover.bmp")).toBeNull();

  await userEvent.click(screen.getByRole("button", { name: "Stop ignoring pattern *.png" }));
  await vi.waitFor(() => expect(puts).toHaveLength(1));
  await userEvent.type(screen.getByLabelText("New pattern"), " *.nfo {Enter}");
  await vi.waitFor(() => expect(puts).toHaveLength(2));
  await userEvent.click(screen.getByRole("button", { name: "Stop ignoring file sub/scan.jpg" }));
  await vi.waitFor(() => expect(puts).toHaveLength(3));
  await userEvent.click(screen.getByRole("button", { name: /Default patterns/ }));
  await vi.waitFor(() => expect(puts).toHaveLength(4));
  expect(puts).toEqual([
    { patterns: ["*.txt"], files: ["sub/scan.jpg"] },
    { patterns: ["*.txt", "*.png", "*.nfo"], files: ["sub/scan.jpg"] },
    { patterns: ["*.txt", "*.png"], files: [] },
    { patterns: null, files: ["sub/scan.jpg"] },
  ]);
});
