import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { queryClient } from "@/lib/queries";
import type { SetCandidates } from "@/lib/types";
import { META } from "@/test/fixtures";
import { AddSetsDialog } from "./AddSetsDialog";

const CANDIDATES: SetCandidates = {
  mount: "roms",
  path: "roms",
  location: "/roms/roms",
  rows: [
    { name: "nes", path: "roms/nes", platform: "nes", note: "matched by its name (NES)", label: "nes", problem: null, items: 3 },
    { name: "misc", path: "roms/misc", platform: null, note: "no platform has this name: pick one or skip it", label: "misc", problem: null, items: 1 },
    { name: "gb", path: "roms/gb", platform: "gb", note: "", label: "", problem: "that folder is already added as 'gb'", items: null },
  ],
}; // biome-ignore format: one row per line

function renderDialog() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = url.endsWith("/meta")
      ? META
      : url.includes("/set-candidates")
        ? CANDIDATES
        : url.includes("/browse")
          ? { mount: "roms", path: "", location: "/roms", children: ["roms"], suggested_label: "" }
          : url.endsWith("/sets")
            ? [{ label: "nes" }]
            : [];
    return new Response(JSON.stringify(body), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <AddSetsDialog open onOpenChange={() => {}} />
    </QueryClientProvider>,
  );
  return calls;
}

test("lists the subfolders with their matches and adds the ticked ones", async () => {
  const calls = renderDialog();
  await userEvent.click(await screen.findByRole("button", { name: "roms" }));
  await userEvent.click(screen.getByRole("button", { name: "List subfolders" }));
  // Matched rows start ticked, unmatched ones unticked, sets already taken cannot be ticked.
  expect(await screen.findByRole("checkbox", { name: "Add nes" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Add misc" })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Add gb" })).toBeDisabled();
  expect(screen.getByText("that folder is already added as 'gb'")).toBeInTheDocument();
  const label = screen.getByRole("textbox", { name: "Label for nes" });
  await userEvent.clear(label);
  await userEvent.type(label, "nes-main");
  await userEvent.click(screen.getByRole("button", { name: "Add 1 set" }));
  const sent = calls.find((c) => c.url.endsWith("/api/sets"));
  expect(JSON.parse(String(sent?.init?.body))).toEqual({
    mount: "roms",
    sets: [{ path: "roms/nes", platform: "nes", label: "nes-main" }],
  });
});
