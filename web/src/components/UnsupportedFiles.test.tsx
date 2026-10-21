import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { UnsupportedFiles } from "@/components/UnsupportedFiles";
import { META } from "@/test/fixtures";

test("lists files outside the platform's formats with the reason and what is supported", () => {
  render(
    <UnsupportedFiles
      platform="nes"
      meta={META}
      files={[
        { rel_path: "Game.fds", size: 2048, reason: ".fds is not a supported format" },
        { rel_path: "Other.zip", size: 10, reason: "no supported ROM inside (it holds .txt)" },
      ]}
    />,
  );
  expect(
    screen.getByText(/2 files not in a supported Nintendo Entertainment System format/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Supported: \.nes, bare or inside \.zip or \.7z/)).toBeInTheDocument();
  expect(screen.getByText(/\.fds is not a supported format/)).toBeInTheDocument();
  expect(screen.getByText(/it holds \.txt/)).toBeInTheDocument();
});

test("nothing is shown when every file is supported", () => {
  const { container } = render(<UnsupportedFiles platform="nes" meta={META} files={[]} />);
  expect(container).toBeEmptyDOMElement();
});

test("the files can be sent for review to move to discarded/", async () => {
  const moved: string[][] = [];
  render(
    <UnsupportedFiles
      platform="nes"
      meta={META}
      files={[{ rel_path: "Game.fds", size: 2048, reason: ".fds is not a supported format" }]}
      onMove={(relPaths) => moved.push(relPaths)}
    />,
  );
  await userEvent.click(screen.getByText(/not in a supported/));
  await userEvent.click(screen.getByRole("button", { name: /Move 1 file to discarded/ }));
  expect(moved).toEqual([["Game.fds"]]);
});
