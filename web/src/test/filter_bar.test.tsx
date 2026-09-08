import { describe, expect, it } from "vitest";
import { matchesFilter } from "../sections/filter";

describe("matchesFilter", () => {
  it("matches when every term is a substring of some field", () => {
    expect(matchesFilter("max play", "max-players", "how many players")).toBe(true);
  });

  it("does not match when a term is absent from all fields", () => {
    expect(matchesFilter("max ghosts", "max-players", "how many players")).toBe(false);
  });

  it("treats an empty or whitespace query as matching everything", () => {
    expect(matchesFilter("", "anything")).toBe(true);
    expect(matchesFilter("   ", "anything")).toBe(true);
  });

  it("is case-insensitive and ignores null/undefined fields", () => {
    expect(matchesFilter("DIFF", null, undefined, "difficulty")).toBe(true);
  });
});
