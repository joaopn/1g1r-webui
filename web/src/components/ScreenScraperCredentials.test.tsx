import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { queryClient } from "@/lib/queries";
import { ScreenScraperCredentials } from "./ScreenScraperCredentials";

const ENVIRONMENT = {
  devid: "SCREENSCRAPER_DEVID",
  devpassword: "SCREENSCRAPER_DEVPASSWORD",
  user: "SCREENSCRAPER_USER",
  password: "SCREENSCRAPER_PASSWORD",
};

test("only typed fields are sent; environment fields are locked; saved ones show as saved", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response("{}", { status: 200 });
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ScreenScraperCredentials
        sources={{ devid: "environment", devpassword: "app", user: null, password: null }}
        environment={ENVIRONMENT}
      />
    </QueryClientProvider>,
  );
  expect(screen.getByLabelText("Developer ID")).toBeDisabled();
  expect(screen.getByLabelText("Developer ID")).toHaveAttribute(
    "placeholder",
    "set by SCREENSCRAPER_DEVID",
  );
  expect(screen.getByLabelText("Developer password")).toHaveAttribute("placeholder", "saved");
  expect(screen.getByRole("button", { name: "Save credentials" })).toBeDisabled();
  await userEvent.type(screen.getByLabelText("Username"), "me");
  await userEvent.click(screen.getByRole("button", { name: "Save credentials" }));
  const put = calls.find((c) => c.init?.method === "PUT");
  expect(put?.url).toMatch(/\/settings\/screenscraper-credentials$/);
  expect(JSON.parse(String(put?.init?.body))).toEqual({ user: "me" });
  await userEvent.click(screen.getByRole("button", { name: "Remove saved credentials" }));
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(true);
});
