import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { UnsupportedFiles } from "@/components/UnsupportedFiles";
import { queryClient } from "@/lib/queries";
import type { FolderInfo } from "@/lib/types";
import { META } from "@/test/fixtures";

const FOLDER: FolderInfo = {
  label: "nes",
  platform: "nes",
  mount: "roms",
  path: "nes",
  location: "/roms/nes",
  on_main_mount: true,
  target: "zip",
  discarded_to: "/roms/discarded/nes/",
  delete_originals: false,
  hidden: false,
  ignored_patterns: ["*.txt"],
  ignored_patterns_default: true,
  ignored_files: ["old.bin"],
  title_ids: false,
  rename_template: "keep",
  rename_templates: ["keep", "dat", "clean"],
};

const wrap = (node: ReactNode) => (
  <QueryClientProvider client={queryClient}>{node}</QueryClientProvider>
);

afterEach(() => {
  vi.unstubAllGlobals();
  queryClient.clear();
});

test("lists files outside the platform's formats with the reason and what is supported", () => {
  render(
    wrap(
      <UnsupportedFiles
        folder={FOLDER}
        meta={META}
        files={[
          { rel_path: "Game.fds", size: 2048, reason: ".fds is not a supported format" },
          { rel_path: "Other.zip", size: 10, reason: "no supported ROM inside (it holds .txt)" },
        ]}
      />,
    ),
  );
  expect(
    screen.getByText(/2 files not in a supported Nintendo Entertainment System format/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Supported: \.nes, bare or inside \.zip or \.7z/)).toBeInTheDocument();
  expect(screen.getByText(/\.fds is not a supported format/)).toBeInTheDocument();
  expect(screen.getByText(/it holds \.txt/)).toBeInTheDocument();
});

test("nothing is shown when every file is supported", () => {
  const { container } = render(wrap(<UnsupportedFiles folder={FOLDER} meta={META} files={[]} />));
  expect(container).toBeEmptyDOMElement();
});

test("the files can be sent for review to move to discarded/", async () => {
  const moved: string[][] = [];
  render(
    wrap(
      <UnsupportedFiles
        folder={FOLDER}
        meta={META}
        files={[{ rel_path: "Game.fds", size: 2048, reason: ".fds is not a supported format" }]}
        onMove={(relPaths) => moved.push(relPaths)}
      />,
    ),
  );
  await userEvent.click(screen.getByText(/not in a supported/));
  await userEvent.click(screen.getByRole("button", { name: /Move 1 file to discarded/ }));
  expect(moved).toEqual([["Game.fds"]]);
});

test("a file, or every file of its format, goes on the set's ignore list", async () => {
  const puts: unknown[] = [];
  vi.stubGlobal("fetch", async (_url: string, init?: RequestInit) => {
    puts.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify({ ...FOLDER, checking: true }), {
      headers: { "Content-Type": "application/json" },
    });
  });
  render(
    wrap(
      <UnsupportedFiles
        folder={FOLDER}
        meta={META}
        files={[
          { rel_path: "sub/Cover.PNG", size: 1, reason: ".png is not a supported format" },
          { rel_path: "Other.zip", size: 10, reason: "no supported ROM inside (it holds .txt)" },
          { rel_path: "README", size: 1, reason: "no file extension" },
        ]}
      />,
    ),
  );
  await userEvent.click(screen.getByText(/not in a supported/));
  await userEvent.click(screen.getByRole("button", { name: "Ignore sub/Cover.PNG" }));
  await vi.waitFor(() => expect(puts).toHaveLength(1));
  await userEvent.click(screen.getByRole("button", { name: "Ignore every *.png file" }));
  await vi.waitFor(() => expect(puts).toHaveLength(2));
  expect(puts).toEqual([
    { patterns: ["*.txt"], files: ["old.bin", "sub/Cover.PNG"] },
    { patterns: ["*.txt", "*.png"], files: ["old.bin"] },
  ]);
  // An archive format also holds ROMs; a file without an extension has no format button.
  expect(screen.getByRole("button", { name: "Ignore every *.zip file" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: /Ignore every .*README/ })).toBeNull();
  expect(screen.getByRole("button", { name: "Ignore README" })).toBeEnabled();
});
