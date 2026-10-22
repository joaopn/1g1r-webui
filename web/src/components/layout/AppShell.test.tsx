import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { META } from "@/test/fixtures";
import { AppShell, navGroups } from "./AppShell";

const FOLDERS = [
  {
    label: "nes",
    platform: "nes",
    mount: "roms",
    path: "nes",
    location: "/roms/nes",
    on_main_mount: true,
    target: "zip",
    discarded_to: "/roms/discarded/nes/",
    scan: null,
    last_scan: null,
    dat: null,
    summary: { counts: {}, roms: 0, bytes: 0, identified: 0, unmatched: 0, methods: {} },
    dat_download: null,
    needs_dat: false,
    needs_scan: false,
    needs: null,
    counts: {},
    reclaim_bytes: 0,
    progress: { processed: 0, to_process: 0, to_match: 0, to_convert: 0 },
    delete_originals: false,
    hidden: false,
    conversion: {
      wrap: 0,
      unwrap: 0,
      "make chd": 0,
      "make rvz": 0,
      byteswap: 0,
      decrypt: 0,
      flagged: 0,
      part: 0,
      repack: 0,
      done: 0,
      to_convert: 0,
      all: 0,
    },
    discarded: { files: 0, bytes: 0 },
    converting: null,
    running: false,
    warnings: [],
  },
];

function renderShell(path = "/", folders = FOLDERS) {
  vi.stubGlobal("fetch", async (url: string) => {
    const body = url.endsWith("/meta")
      ? META
      : url.endsWith("/folders")
        ? folders
        : url.includes("/browse")
          ? { mount: "roms", path: "", location: "/roms", children: [], suggested_label: "" }
          : [];
    return new Response(JSON.stringify(body), { status: 200 });
  });
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="*" element={<p>page</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => window.localStorage.clear());

test("groups start closed and open on click, with the chevron turning", async () => {
  renderShell();
  const romsets = (await screen.findAllByRole("button", { name: /Romsets/ }))[0];
  expect(romsets).toHaveAttribute("aria-expanded", "false");
  expect(screen.getAllByTestId("chevron-romsets")[0]).not.toHaveClass("rotate-90");
  await userEvent.click(romsets);
  expect(romsets).toHaveAttribute("aria-expanded", "true");
  expect(screen.getAllByTestId("chevron-romsets")[0]).toHaveClass("rotate-90");
  expect(await screen.findAllByTitle("Nintendo Entertainment System · nes")).not.toHaveLength(0);
  await userEvent.click(romsets);
  expect(romsets).toHaveAttribute("aria-expanded", "false");
});

test("one Romsets group replaces the per-page groups", async () => {
  renderShell();
  await screen.findAllByRole("button", { name: /Romsets/ });
  for (const name of [/^Conversion$/, /Matching & 1G1R/, /^Discarded$/]) {
    expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
  }
});

test("a set's entry stays open and highlighted on every one of its tabs", async () => {
  renderShell("/folders/nes/discarded");
  const romsets = (await screen.findAllByRole("button", { name: /Romsets/ }))[0];
  await waitFor(() => expect(romsets).toHaveAttribute("aria-expanded", "true"));
  const entry = screen.getAllByTitle("Nintendo Entertainment System · nes")[0];
  expect(entry).toHaveClass("bg-sidebar-accent");
});

test("a set's entry opens Conversion when it has conversion work, else Matching", () => {
  const folder = FOLDERS[0];
  const converting = { ...folder, label: "gb", progress: { ...folder.progress, to_convert: 1 } };
  const idle = { ...folder, progress: { ...folder.progress, to_convert: 0 } };
  const romsets = navGroups([converting, idle], META).find((g) => g.id === "romsets");
  expect(romsets?.children.map((c) => c.to).sort()).toEqual([
    "/folders/gb/conversion",
    "/folders/nes/matching",
  ]);
});

test("the sidebar is resized with the keyboard and remembers its width", async () => {
  renderShell();
  const handle = await screen.findByTestId("sidebar-resize");
  handle.focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(screen.getByTestId("sidebar")).toHaveStyle({
    width: `${META.ui.sidebar.width_rem + META.ui.resize_step_rem}rem`,
  });
  expect(window.localStorage.getItem("g1r.sidebar.width.v1")).toBe(
    String(META.ui.sidebar.width_rem + META.ui.resize_step_rem),
  );
});

test("folders are listed by platform name, then label", () => {
  const folder = FOLDERS[0];
  const folders = [
    folder,
    { ...folder, label: "gb-2", platform: "gb" },
    { ...folder, label: "gb", platform: "gb" },
  ];
  const romsets = navGroups(folders, META).find((g) => g.id === "romsets");
  expect(romsets?.children.map((c) => c.title)).toEqual([
    "Game Boy · gb",
    "Game Boy · gb-2",
    "Nintendo Entertainment System · nes",
  ]);
});

test("hidden sets stay out of the sidebar, and both ways to add sets are at its foot", async () => {
  renderShell("/", [...FOLDERS, { ...FOLDERS[0], label: "gb", platform: "gb", hidden: true }]);
  await userEvent.click((await screen.findAllByRole("button", { name: /Romsets/ }))[0]);
  expect(await screen.findAllByTitle("Nintendo Entertainment System · nes")).not.toHaveLength(0);
  expect(screen.queryByTitle("Game Boy · gb")).not.toBeInTheDocument();
  expect(screen.queryByTestId("add-set")).not.toBeInTheDocument();
  expect(screen.queryByTestId("add-sets")).not.toBeInTheDocument();
  expect(screen.getAllByTestId("add-romsets")[0]).toHaveTextContent("Add romsets");
});

test("Add romsets offers both ways to add sets, each opening its own dialog", async () => {
  renderShell();
  await userEvent.click((await screen.findAllByTestId("add-romsets"))[0]);
  const chooser = await screen.findByRole("dialog", { name: "Add romsets" });
  expect(chooser).toHaveTextContent("Add single folder");
  await userEvent.click(screen.getByRole("button", { name: "Automatch folders" }));
  expect(await screen.findByRole("dialog", { name: "Automatch folders" })).toBeInTheDocument();
  expect(screen.queryByRole("dialog", { name: "Add romsets" })).not.toBeInTheDocument();
  await userEvent.keyboard("{Escape}");
  await userEvent.click(screen.getAllByTestId("add-romsets")[0]);
  await userEvent.click(await screen.findByRole("button", { name: "Add single folder" }));
  expect(await screen.findByRole("dialog", { name: "Add single folder" })).toBeInTheDocument();
});

test("the theme toggle is an icon at the top of the sidebar and cycles", async () => {
  renderShell();
  const toggle = (await screen.findAllByTestId("theme-toggle"))[0];
  const before = toggle.textContent;
  await userEvent.click(toggle);
  expect(toggle.textContent).not.toBe(before);
  expect(toggle.textContent).toMatch(/^Theme: /);
});

test("the bell sits beside the theme toggle and the license line in the sidebar foot", async () => {
  renderShell();
  const sidebar = await screen.findByTestId("sidebar");
  await waitFor(() => expect(within(sidebar).getByTestId("notifications")).toBeInTheDocument());
  expect(within(sidebar).getByTestId("theme-toggle")).toBeInTheDocument();
  expect(within(sidebar).getByTestId("license")).toHaveTextContent(/^License: AGPL 3\.0 · /);
  expect(screen.queryByRole("contentinfo")).toBeNull();
});
