import { render, screen } from "@testing-library/react";
import { Box } from "./Box";

test("only the background is clipped, so a popover from the buttons can leave the panel", () => {
  render(
    <Box
      title="Matching"
      background={<div data-testid="fill" />}
      actions={<button type="button">DAT order</button>}
    >
      text
    </Box>,
  );
  expect(screen.getByRole("region", { name: "Matching" })).not.toHaveClass("overflow-hidden");
  expect(screen.getByTestId("fill").parentElement).toHaveClass("overflow-hidden");
});
