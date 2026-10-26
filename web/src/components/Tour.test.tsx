import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import type { FolderCard } from "@/lib/types";
import { FOLDER_CARD, META } from "@/test/fixtures";
import { TOUR_KEY, tourStep } from "./Tour";

const set = (fields: Partial<FolderCard>) => ({ ...FOLDER_CARD, ...fields }) as FolderCard;

test("the tour's step is the first one still open", () => {
  expect(tourStep(undefined)).toBeNull();
  expect(tourStep([])).toBe("add");
  expect(tourStep([set({ hidden: true })])).toBe("add");
  expect(tourStep([set({ needs_dat: true, needs_scan: true })])).toBe("dats");
  expect(tourStep([set({ needs_dat: true, hidden: true }), set({ needs_scan: true })])).toBe(
    "scan",
  );
  expect(tourStep([set({})])).toBe("done");
  const running = { ...FOLDER_CARD.scan, status: "running" } as FolderCard["scan"];
  expect(tourStep([set({ scan: running })])).toBeNull();
});

function renderShell(folders: FolderCard[]) {
  vi.stubGlobal("fetch", async (url: string) => {
    const body = url.endsWith("/meta") ? META : url.endsWith("/folders") ? folders : [];
    return new Response(JSON.stringify(body), { status: 200 });
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="*" element={<p>page</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// jsdom lays nothing out: every element counts as on screen.
beforeEach(() => {
  window.localStorage.clear();
  vi.spyOn(Element.prototype, "getClientRects").mockReturnValue([
    new DOMRect(),
  ] as unknown as DOMRectList);
});
afterEach(() => vi.restoreAllMocks());

const title = () => document.querySelector(".driver-popover-title");

test("without a set the tour points at Add romsets; Skip ends it for good", async () => {
  renderShell([]);
  await waitFor(() => expect(title()).toHaveTextContent("Add romsets"));
  expect(screen.getAllByTestId("add-romsets")[0]).toHaveClass("driver-active-element");
  const skip = document.querySelector<HTMLElement>(".driver-popover-next-btn");
  expect(skip).toHaveTextContent("Skip tour");
  expect(skip).toBeVisible();
  if (skip) await userEvent.click(skip);
  await waitFor(() => expect(title()).toBeNull());
  expect(JSON.parse(window.localStorage.getItem(TOUR_KEY) ?? "null")).toBe(true);
});

test("clicking the lit control does its job and hides the mark", async () => {
  renderShell([]);
  await waitFor(() => expect(title()).toHaveTextContent("Add romsets"));
  await userEvent.click(screen.getAllByTestId("add-romsets")[0]);
  await waitFor(() => expect(title()).toBeNull());
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(window.localStorage.getItem(TOUR_KEY)).toBeNull();
});

test("a set without a DAT points at Platform DATs", async () => {
  renderShell([set({ label: "nes", platform: "nes", needs_dat: true })]);
  await waitFor(() => expect(title()).toHaveTextContent("Platform DATs"));
});

test("a finished tour does not come back", async () => {
  window.localStorage.setItem(TOUR_KEY, "true");
  renderShell([]);
  await screen.findAllByTestId("add-romsets");
  await new Promise((done) => requestAnimationFrame(done));
  expect(title()).toBeNull();
});
