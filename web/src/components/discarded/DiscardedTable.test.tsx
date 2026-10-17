import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { Discarded } from "@/lib/types";
import { META } from "@/test/fixtures";
import { DiscardedTable } from "./DiscardedTable";

const file = (rel_path: string, extra = {}) => ({
  rel_path,
  size: 2048,
  modified: "2026-10-17T10:00:00Z",
  restore_to: `/roms/nes/${rel_path}`,
  occupied: false,
  operation_id: null,
  ...extra,
});

const DATA: Discarded = {
  root: "/roms/discarded/nes",
  files: 3,
  bytes: 6144,
  reasons: [
    {
      id: "1g1r",
      label: "1G1R",
      description: "",
      known: true,
      bytes: 4096,
      files: [file("Contra (Japan).zip", { occupied: true }), file("Gradius (USA).zip")],
    },
    {
      id: "originals",
      label: "Originals",
      description: "",
      known: true,
      bytes: 2048,
      files: [file("Bare (Europe).nes", { restore_to: null })],
    },
  ],
};

function renderTable() {
  render(
    <MemoryRouter>
      <DiscardedTable data={DATA} meta={META} />
    </MemoryRouter>,
  );
}

test("every file is listed with its reason and where Restore would put it", () => {
  renderTable();
  expect(screen.getAllByTestId(/^discarded-/)).toHaveLength(3);
  const taken = screen.getByTestId("discarded-Contra (Japan).zip");
  expect(within(taken).getByText("1G1R")).toBeInTheDocument();
  expect(within(taken).getByText(/already there/)).toBeInTheDocument();
  expect(
    within(screen.getByTestId("discarded-Bare (Europe).nes")).getByText("folder unavailable"),
  ).toBeInTheDocument();
});

test("a quick view per reason narrows the list", async () => {
  renderTable();
  const bar = screen.getByTestId("quick-views");
  await userEvent.click(within(bar).getByText("Originals"));
  expect(screen.getAllByTestId(/^discarded-/)).toHaveLength(1);
  await userEvent.type(screen.getByLabelText("Search files"), "zzz");
  expect(screen.getByText("No files match.")).toBeInTheDocument();
});

test("files the app moved have a Restore button; others say who put them there", async () => {
  const onRestore = vi.fn();
  const data: Discarded = {
    ...DATA,
    reasons: [
      {
        ...DATA.reasons[0],
        files: [file("Gradius (USA).zip", { operation_id: 4 }), file("Other.zip")],
      },
    ],
  };
  render(
    <MemoryRouter>
      <DiscardedTable data={data} meta={META} onRestore={onRestore} />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole("button", { name: "Restore Gradius (USA).zip" }));
  expect(onRestore).toHaveBeenCalledWith(4);
  expect(
    within(screen.getByTestId("discarded-Other.zip")).getByText("not moved here by this app"),
  ).toBeInTheDocument();
});
