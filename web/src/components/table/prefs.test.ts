import { expect, test } from "vitest";
import { template } from "./prefs";

const SIZES = {
  name: { rem: 12, min: 8, max: 40 },
  size: { rem: 5, min: 4, max: 10 },
};

test("every column stretches from its width, in proportion to it", () => {
  expect(template(["name", "size"], SIZES, {})).toBe("minmax(12rem, 12fr) minmax(5rem, 5fr)");
});

test("a resized column keeps its width while the others stretch", () => {
  expect(template(["name", "size"], SIZES, { size: 6 })).toBe("minmax(12rem, 12fr) 6rem");
});

test("when every column is resized, they all stretch again", () => {
  expect(template(["name", "size"], SIZES, { name: 20, size: 6 })).toBe(
    "minmax(20rem, 20fr) minmax(6rem, 6fr)",
  );
});
