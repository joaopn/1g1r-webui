import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ConvertPreview } from "@/lib/types";
import { META } from "@/test/fixtures";
import { ConvertDialog } from "./ConvertDialog";

const CONVERSION = {
  rel_path: "Tetris (World).gb",
  output: "Tetris (World).zip",
  size: 32768,
  original_to: "/roms/discarded/gb/originals/Tetris (World).gb",
};

function renderDialog(preview: ConvertPreview) {
  const calls: { url: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    calls.push({ url, body: init.body ? JSON.parse(String(init.body)) : null });
    const body = url.endsWith("/preview") ? preview : { status: "running" };
    return new Response(JSON.stringify(body), { status: 200 });
  });
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ConvertDialog
        label="gb"
        relPaths={null}
        title="Convert files in gb"
        meta={META}
        open
        onOpenChange={onOpenChange}
      />
    </QueryClientProvider>,
  );
  return { calls, onOpenChange };
}

const PLAN = { token: "t1", bytes: 32768, problems: [], busy: null };

test("lists each conversion and converts with the plan's token", async () => {
  const { calls, onOpenChange } = renderDialog({
    ...PLAN,
    conversions: [CONVERSION],
    irreversible: 0,
  });
  expect(await screen.findByText("Tetris (World).zip")).toBeInTheDocument();
  expect(screen.queryByTestId("convert-guard")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Convert 1 file" }));
  expect(calls.at(-1)).toEqual({ url: "/api/folders/gb/convert", body: { token: "t1" } });
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

test("deleting originals needs the folder label typed", async () => {
  const { calls } = renderDialog({
    ...PLAN,
    conversions: [{ ...CONVERSION, original_to: null }],
    irreversible: 1,
  });
  expect(await screen.findByText("original deleted")).toBeInTheDocument();
  const button = screen.getByRole("button", { name: "Convert 1 file" });
  expect(button).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Folder label"), "g");
  expect(button).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Folder label"), "b");
  await userEvent.click(button);
  expect(calls.at(-1)).toEqual({
    url: "/api/folders/gb/convert",
    body: { token: "t1", confirm: "gb" },
  });
});
