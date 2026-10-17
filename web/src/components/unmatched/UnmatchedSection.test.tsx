import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { queryClient } from "@/lib/queries";
import type { UnmatchedFile } from "@/lib/types";
import { META } from "@/test/fixtures";
import { UnmatchedSection } from "./UnmatchedSection";

const FILES: UnmatchedFile[] = [
  {
    rel_path: "Doraemon (Japan) (Rev 1).zip",
    size: 163856,
    hash: { crc32: "83348047", sha1: "71322777250ea6573554ea04538f1b2ae9b76b83" },
    hasheous: { status: "not found", detail: "" },
    suggestions: [{ game_name: "Doraemon (Japan)", score: 0.84 }],
  },
];

const PREVIEW = {
  token: "t",
  files: [{ rel_path: FILES[0].rel_path, size: FILES[0].size, destination: null }],
  irreversible: 1,
  bytes: FILES[0].size,
  problems: [],
  busy: null,
};

function renderSection(hasheousOn: boolean) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = url.endsWith("/unmatched/preview")
      ? PREVIEW
      : url.endsWith("/unmatched")
        ? FILES
        : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <UnmatchedSection label="nes" meta={META} hasheousOn={hasheousOn} scanning={false} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

test("lists the file with what Hasheous said, and a suggestion assigns it", async () => {
  const calls = renderSection(true);
  const suggestion = await screen.findByRole("button", { name: /^Doraemon \(Japan\)/ });
  expect(screen.getByText("Hasheous: not found online")).toBeInTheDocument();
  expect(screen.getByText(/84%/)).toBeInTheDocument();
  await userEvent.click(suggestion);
  const put = calls.find((c) => c.url.endsWith("/assign"));
  expect(JSON.parse(String(put?.init?.body))).toEqual({
    rel_path: "Doraemon (Japan) (Rev 1).zip",
    game_name: "Doraemon (Japan)",
  });
});

test("with lookups off it links to the settings instead of offering a retry", async () => {
  renderSection(false);
  expect(await screen.findByText("Online lookups are off")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Look up again/ })).not.toBeInTheDocument();
});

test("deleting a file asks for the folder label first", async () => {
  const calls = renderSection(false);
  await userEvent.click(
    await screen.findByRole("button", { name: "Delete Doraemon (Japan) (Rev 1).zip" }),
  );
  const run = await screen.findByRole("button", { name: "Delete 1 file" });
  expect(run).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Folder label"), "nes");
  await userEvent.click(run);
  const sent = calls.find((c) => c.url === "/api/folders/nes/unmatched" && c.init?.body);
  expect(JSON.parse(String(sent?.init?.body))).toEqual({
    rel_paths: ["Doraemon (Japan) (Rev 1).zip"],
    delete: true,
    token: "t",
    confirm: "nes",
  });
});
