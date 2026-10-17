import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ApplyPreview } from "@/lib/types";
import { META } from "@/test/fixtures";
import { ApplyDialog } from "./ApplyDialog";

const MOVE = {
  rel_path: "Contra (Japan).zip",
  group_key: "name:Contra",
  source: "/roms/nes/Contra (Japan).zip",
  destination: "/roms/discarded/nes/1g1r/Contra (Japan).zip",
  size: 2048,
};

function renderDialog(preview: ApplyPreview) {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    calls.push({ url, body: init.body ? JSON.parse(String(init.body)) : null });
    const body = url.endsWith("/preview") ? preview : { status: "running" };
    return new Response(JSON.stringify(body), { status: 200 });
  });
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ApplyDialog
        label="nes"
        groupKey={null}
        title="Apply 1G1R to nes"
        meta={META}
        open
        onOpenChange={onOpenChange}
      />
    </QueryClientProvider>,
  );
  return { calls, onOpenChange };
}

test("lists the plan and applies it with its token", async () => {
  const { calls, onOpenChange } = renderDialog({
    token: "t1",
    moves: [MOVE],
    bytes: 2048,
    problems: [],
    busy: null,
  });
  expect(await screen.findByText("Contra (Japan).zip")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Move 1 file to discarded/" }));
  expect(calls.at(-1)).toEqual({ url: "/api/folders/nes/apply", body: { token: "t1" } });
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

test("a plan with problems cannot be applied", async () => {
  renderDialog({
    token: "t2",
    moves: [MOVE],
    bytes: 2048,
    problems: [{ rel_path: MOVE.rel_path, problem: "it changed since it was scanned" }],
    busy: null,
  });
  expect(await screen.findByText("it changed since it was scanned")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Move 1 file to discarded/" })).toBeDisabled();
});
