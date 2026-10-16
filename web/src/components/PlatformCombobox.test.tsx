import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { platformsByName } from "@/lib/platforms";
import { META } from "@/test/fixtures";
import { PlatformCombobox } from "./PlatformCombobox";

const PLATFORMS = platformsByName(META.platforms);

function renderBox(value = "", onChange = vi.fn()) {
  render(
    <PlatformCombobox id="platform" platforms={PLATFORMS} value={value} onChange={onChange} />,
  );
  return { onChange, input: screen.getByRole("combobox") };
}

const options = () => screen.getAllByRole("option").map((o) => o.textContent);

test("lists every platform by name, and typing narrows the list", async () => {
  const { input } = renderBox();
  await userEvent.click(input);
  expect(options()).toEqual(["GBGame Boy", "NESNintendo Entertainment System"]);
  await userEvent.type(input, "nint");
  expect(options()).toEqual(["NESNintendo Entertainment System"]);
  await userEvent.clear(input);
  await userEvent.type(input, "gb");
  expect(options()).toEqual(["GBGame Boy"]);
});

test("arrow keys and Enter pick a platform, and the field then shows it", async () => {
  const { input, onChange } = renderBox();
  await userEvent.click(input);
  await userEvent.keyboard("{ArrowDown}{Enter}");
  expect(onChange).toHaveBeenCalledWith("nes");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

test("a click picks; Escape closes without picking", async () => {
  const { input, onChange } = renderBox("gb");
  expect(input).toHaveValue("Game Boy");
  await userEvent.click(input);
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(onChange).not.toHaveBeenCalled();
  await userEvent.click(input);
  await userEvent.click(screen.getByRole("option", { name: /Nintendo/ }));
  expect(onChange).toHaveBeenCalledWith("nes");
});

test("no match says so", async () => {
  const { input } = renderBox();
  await userEvent.type(input, "vita");
  expect(screen.getByText("No supported platform")).toBeInTheDocument();
});
