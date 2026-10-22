import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { keys, queryClient } from "@/lib/queries";
import type { Notification } from "@/lib/types";
import { META } from "@/test/fixtures";
import { Notifications } from "./Notifications";

const item = (over: Partial<Notification>): Notification => ({
  id: "run-1",
  kind: "1g1r",
  title: "1G1R apply",
  folder_label: "nes",
  status: "done",
  started_at: "2026-10-21T10:00:00Z",
  finished_at: "2026-10-21T10:01:00Z",
  message: "2 files moved to discarded/",
  stage: null,
  done: 2,
  total: 2,
  failed: 0,
  ...over,
});

const FEED = [
  item({
    id: "scan-4",
    kind: "scan",
    title: "Scan",
    status: "running",
    stage: "Hashing",
    done: 3,
    total: 10,
    finished_at: null,
  }),
  item({
    id: "run-3",
    kind: "conversion",
    title: "Conversion",
    status: "failed",
    message: "1 file converted; 1 failed",
  }),
  item({ id: "run-2", folder_label: "gone" }),
];

function setup(feed = FEED) {
  const deletes: string[] = [];
  let current = feed;
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      deletes.push(url);
      current = current.filter(
        (n) => n.status === "running" || (!url.endsWith("/notifications") && !url.endsWith(n.id)),
      );
      return new Response(null, { status: 204 });
    }
    const body = url.endsWith("/notifications")
      ? current
      : url.endsWith("/folders")
        ? [{ label: "nes" }]
        : META;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  queryClient.clear();
  queryClient.setQueryData(keys.meta, META);
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Notifications />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return deletes;
}

// Items seen before the tests' own feed: none.
beforeEach(() => localStorage.setItem("g1r.notifications.seen.v1", "[]"));

test("the bell counts unread items, the panel lists them and Clear keeps running ones", async () => {
  const deletes = setup();
  const user = userEvent.setup();
  const unread = await screen.findByTestId("notifications-unread");
  expect(unread).toHaveTextContent("2");
  expect(unread.className).toContain("bg-status-bad");
  expect(screen.getByTestId("notifications")).toHaveAccessibleName(
    "Notifications, 1 running, 2 new",
  );

  await user.click(screen.getByTestId("notifications"));
  const scan = screen.getByTestId("notification-scan-4");
  expect(scan).toHaveTextContent("Hashing: 3 / 10 files");
  expect(within(scan).queryByRole("button")).toBeNull();
  const failed = screen.getByTestId("notification-run-3");
  expect(failed).toHaveTextContent("1 file converted; 1 failed");
  expect(within(failed).getByRole("link", { name: "nes" })).toHaveAttribute(
    "href",
    "/folders/nes/conversion",
  );
  // A set that was removed is named without a link.
  expect(within(screen.getByTestId("notification-run-2")).queryByRole("link")).toBeNull();

  await user.click(within(failed).getByRole("button", { name: /Dismiss/ }));
  await waitFor(() => expect(screen.queryByTestId("notification-run-3")).toBeNull());
  expect(deletes).toEqual(["/api/notifications/run-3"]);

  await user.click(screen.getByTestId("notifications-clear"));
  await waitFor(() => expect(screen.queryByTestId("notification-run-2")).toBeNull());
  expect(deletes.at(-1)).toBe("/api/notifications");
  expect(screen.getByTestId("notification-scan-4")).toBeInTheDocument();
});

test("closing the panel marks what it showed as read", async () => {
  setup([item({})]);
  const user = userEvent.setup();
  await screen.findByTestId("notifications-unread");
  await user.click(screen.getByTestId("notifications"));
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByTestId("notifications-unread")).toBeNull());
  expect(JSON.parse(localStorage.getItem("g1r.notifications.seen.v1") ?? "[]")).toEqual(["run-1"]);
});

test("a first visit counts what is already listed as read", async () => {
  localStorage.clear();
  setup();
  await waitFor(() =>
    expect(JSON.parse(localStorage.getItem("g1r.notifications.seen.v1") ?? "null")).toEqual([
      "run-3",
      "run-2",
    ]),
  );
  expect(screen.queryByTestId("notifications-unread")).toBeNull();
  expect(screen.getByTestId("notifications-running")).toBeInTheDocument();
});

test("nothing to show", async () => {
  setup([]);
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("notifications"));
  expect(await screen.findByText("No notifications.")).toBeInTheDocument();
  expect(screen.getByTestId("notifications-clear")).toBeDisabled();
});

test("each item opens the page of its set where that work shows", async () => {
  setup([
    item({ id: "scan-9", kind: "check", title: "Check files", message: "3 files checked" }),
    item({ id: "scan-8", kind: "scan", title: "Scan", message: "3 files identified" }),
    item({ id: "run-7", kind: "set-aside", title: "Moved to discarded/" }),
    item({ id: "run-6", kind: "restore", title: "Restore" }),
  ]);
  await userEvent.click(await screen.findByTestId("notifications"));
  const pages = ["scan-9", "scan-8", "run-7", "run-6"].map((id) =>
    within(screen.getByTestId(`notification-${id}`))
      .getByRole("link", { name: "nes" })
      .getAttribute("href"),
  );
  expect(pages).toEqual([
    "/folders/nes/conversion",
    "/folders/nes/matching",
    "/folders/nes/discarded",
    "/folders/nes/discarded",
  ]);
  // The link stretches over the whole item, so a click anywhere on it opens the set.
  expect(within(screen.getByTestId("notification-scan-9")).getByRole("link")).toHaveClass(
    "after:inset-0",
  );
});
