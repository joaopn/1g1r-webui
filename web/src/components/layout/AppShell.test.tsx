import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { META } from "@/test/fixtures";
import { AppShell } from "./AppShell";

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
    dat: null,
    summary: { counts: {}, roms: 0, identified: 0, unmatched: 0, methods: {} },
    counts: {},
    reclaim_bytes: 0,
  },
];

function renderShell(path = "/") {
  vi.stubGlobal("fetch", async (url: string) => {
    const body = url.endsWith("/meta") ? META : url.endsWith("/folders") ? FOLDERS : [];
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
  const matching = (await screen.findAllByRole("button", { name: /Matching & 1G1R/ }))[0];
  expect(matching).toHaveAttribute("aria-expanded", "false");
  expect(screen.getAllByTestId("chevron-matching")[0]).not.toHaveClass("rotate-90");
  await userEvent.click(matching);
  expect(matching).toHaveAttribute("aria-expanded", "true");
  expect(screen.getAllByTestId("chevron-matching")[0]).toHaveClass("rotate-90");
  expect(await screen.findAllByTitle("Nintendo Entertainment System · nes")).not.toHaveLength(0);
  await userEvent.click(matching);
  expect(matching).toHaveAttribute("aria-expanded", "false");
});

test("the group of the current page opens itself", async () => {
  renderShell("/folders/nes/matching");
  const matching = (await screen.findAllByRole("button", { name: /Matching & 1G1R/ }))[0];
  await waitFor(() => expect(matching).toHaveAttribute("aria-expanded", "true"));
  expect(screen.getAllByRole("button", { name: /Conversion/ })[0]).toHaveAttribute(
    "aria-expanded",
    "false",
  );
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
