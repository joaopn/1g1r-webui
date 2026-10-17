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

function renderSection(hasheousOn: boolean) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = url.endsWith("/unmatched") ? FILES : {};
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
  const suggestion = await screen.findByRole("button", { name: /Doraemon \(Japan\)/ });
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
