import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { FolderInfo } from "@/lib/types";
import { META } from "@/test/fixtures";
import { FolderHeader } from "./FolderHeader";

const FOLDER: FolderInfo = {
  label: "nes",
  platform: "nes",
  mount: "roms",
  path: "nes",
  location: "/roms/nes",
  on_main_mount: true,
  target: "/roms/nes",
  discarded_to: "/roms/discarded/nes/",
  delete_originals: false,
  hidden: false,
};

test("the set's pages are tabs, the current one marked", () => {
  render(
    <MemoryRouter>
      <FolderHeader folder={FOLDER} meta={META} section="matching" />
    </MemoryRouter>,
  );
  const tabs = screen.getByRole("navigation", { name: "Set pages" });
  const links = Array.from(tabs.querySelectorAll("a"));
  expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
    ["Conversion", "/folders/nes/conversion"],
    ["Matching & 1G1R", "/folders/nes/matching"],
    ["Discarded", "/folders/nes/discarded"],
  ]);
  expect(screen.getByRole("link", { name: "Matching & 1G1R" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.getByRole("link", { name: "Conversion" })).not.toHaveAttribute("aria-current");
  expect(screen.getByText("/roms/nes")).toBeInTheDocument();
});
