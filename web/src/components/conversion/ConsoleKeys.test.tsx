import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { queryClient } from "@/lib/queries";
import type { KeyStatus } from "@/lib/types";
import { ConsoleKeys } from "./ConsoleKeys";

function renderKeys(status: KeyStatus, after: KeyStatus) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = url.endsWith("/keys") ? status : after;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <ConsoleKeys label="3ds" />
    </QueryClientProvider>,
  );
  return calls;
}

test("says what is missing and uploads boot9 from a file", async () => {
  const calls = renderKeys(
    { boot9: false, seeddb: null, prod_keys: null },
    { boot9: true, seeddb: null, prod_keys: null },
  );
  expect(await screen.findByText(/· missing/)).toBeInTheDocument();
  expect(screen.getByText(/· not added/)).toBeInTheDocument();
  const file = new File([new Uint8Array(4)], "boot9.bin");
  await userEvent.upload(screen.getByLabelText("boot9 file"), file);
  const sent = calls.find((c) => c.url.endsWith("/keys/boot9"));
  expect(sent?.init?.method).toBe("POST");
  expect(sent?.init?.body instanceof FormData && sent.init.body.get("file")).toBeInstanceOf(File);
  expect(await screen.findByText(/· added/)).toBeInTheDocument();
});

test("stored keys show the seed count and can be removed", async () => {
  const calls = renderKeys(
    { boot9: true, seeddb: 1861, prod_keys: null },
    { boot9: true, seeddb: null, prod_keys: null },
  );
  expect(await screen.findByText(/1,861 seeds/)).toBeInTheDocument();
  const removes = screen.getAllByRole("button", { name: "Remove" });
  await userEvent.click(removes[1]);
  expect(calls.some((c) => c.url.endsWith("/keys/seeddb") && c.init?.method === "DELETE")).toBe(
    true,
  );
  expect(await screen.findByText(/· not added/)).toBeInTheDocument();
});
