import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CONVERSION_ROWS, META } from "@/test/fixtures";
import { ConversionTable } from "./ConversionTable";

function renderTable(rows = CONVERSION_ROWS) {
  render(
    <MemoryRouter>
      <ConversionTable rows={rows} meta={META} />
    </MemoryRouter>,
  );
}

const files = () =>
  screen
    .getAllByTestId(/^conversion-/)
    .map((row) => row.getAttribute("data-testid")?.replace("conversion-", ""));

test("proposed steps come first, and the original's destination is shown", () => {
  renderTable();
  expect(files()[0]).toBe("Bare (Europe).nes");
  const wrap = screen.getByTestId("conversion-Bare (Europe).nes");
  expect(within(wrap).getByText("zip it")).toBeInTheDocument();
  expect(within(wrap).getByText("Bare (Europe).zip")).toBeInTheDocument();
  expect(within(wrap).getByText(/discarded\/nes\/originals\/Bare/)).toBeInTheDocument();
});

test("an irreversible step says the original is deleted", () => {
  renderTable(
    CONVERSION_ROWS.map((r) => (r.output ? { ...r, originals_to: null, reversible: false } : r)),
  );
  expect(
    within(screen.getByTestId("conversion-Bare (Europe).nes")).getByText("deleted"),
  ).toBeInTheDocument();
});

test("the quick views narrow the list, with counts", async () => {
  renderTable();
  const bar = screen.getByTestId("quick-views");
  expect(within(bar).getByText("To convert").parentElement).toHaveTextContent("1");
  await userEvent.click(within(bar).getByRole("radio", { name: /Flagged/ }));
  expect(files()).toEqual(["Two.zip"]);
  expect(screen.getByText("2 ROM files in one archive")).toBeInTheDocument();
});

test("search and sorting by file", async () => {
  renderTable();
  await userEvent.click(screen.getByTestId("sort-file"));
  expect(files()).toEqual(["Bare (Europe).nes", "Contra (USA).zip", "Seven.7z", "Two.zip"]);
  await userEvent.type(screen.getByLabelText("Search files"), "contra");
  expect(files()).toEqual(["Contra (USA).zip"]);
});
