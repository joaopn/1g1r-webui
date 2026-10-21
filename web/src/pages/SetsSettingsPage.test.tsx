import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { queryClient } from "@/lib/queries";
import { META } from "@/test/fixtures";
import { SetsSettingsPage } from "./SetsSettingsPage";

const SET = {
  label: "nes",
  platform: "nes",
  mount: "roms",
  path: "nes",
  location: "/roms/nes",
  discarded_to: "/roms/discarded/nes/",
  hidden: false,
  discarded: { files: 2, bytes: 2048 },
  converting: null,
};

function renderPage() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    const body = url.endsWith("/meta")
      ? META
      : url.endsWith("/folders")
        ? [
            SET,
            {
              ...SET,
              label: "gb",
              platform: "gb",
              hidden: true,
              discarded: { files: 0, bytes: 0 },
              converting: null,
            },
          ]
        : {};
    return new Response(JSON.stringify(body), { status: 200 });
  });
  queryClient.clear();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SetsSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return calls;
}

test("every set is listed, hidden ones too, and can be hidden, shown or removed", async () => {
  const calls = renderPage();
  expect(await screen.findByText("hidden")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Show" }));
  const put = calls.find((c) => c.url.endsWith("/folders/gb/hidden"));
  expect(JSON.parse(String(put?.init?.body))).toEqual({ hidden: false });

  const removes = screen.getAllByRole("button", { name: "Remove" });
  await userEvent.click(removes[removes.length - 1]);
  expect(await screen.findByText(/Remove the set nes\?/)).toBeInTheDocument();
  expect(screen.getByText(/no file is touched/)).toBeInTheDocument();
  expect(screen.getByText(/stay there/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Remove set" }));
  expect(calls.some((c) => c.url.endsWith("/folders/nes") && c.init?.method === "DELETE")).toBe(
    true,
  );
});
