import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Meta, Ranking } from "@/lib/types";
import { RankingEditor } from "./RankingEditor";

const RANKING = {
  criteria: ["prerelease", "region"],
  regions: ["World", "USA"],
  languages: ["En"],
  multi_region: "best",
} as Ranking;

const META = {
  ranking: {
    criteria: ["prerelease", "region", "revision"],
    labels: {
      prerelease: "full release over pre-release",
      region: "region priority",
      revision: "newest revision",
    },
    default: RANKING,
  },
} as unknown as Meta;

test("each criterion shows whether it is used; switching saves the criteria that are on", async () => {
  const onSave = vi.fn();
  render(<RankingEditor meta={META} ranking={RANKING} isDefault onSave={onSave} />);
  await userEvent.click(screen.getByTestId("ranking-button"));
  const region = screen.getByRole("checkbox", { name: "Use region priority" });
  const revision = screen.getByRole("checkbox", { name: "Use newest revision" });
  // The text next to each checkbox is the criterion's state, not the action.
  expect(region).toBeChecked();
  expect(region.parentElement).toHaveTextContent("on");
  expect(revision).not.toBeChecked();
  expect(revision.parentElement).toHaveTextContent("off");
  await userEvent.click(region);
  await userEvent.click(screen.getByRole("checkbox", { name: "Use newest revision" }));
  expect(screen.getByRole("checkbox", { name: "Use region priority" })).not.toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Save ranking" }));
  expect(onSave).toHaveBeenCalledWith(
    expect.objectContaining({ criteria: ["prerelease", "revision"] }),
  );
});
