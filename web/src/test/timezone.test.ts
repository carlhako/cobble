import { describe, expect, it } from "vitest";
import {
  dismissMismatch,
  formatInZone,
  isMismatchDismissed,
  zonesMatch,
} from "../api/timezone";

describe("formatInZone", () => {
  it("shows an instant in the named zone and names it, whatever the test's TZ", () => {
    const text = formatInZone("2026-10-07T04:00:00+00:00", "UTC");
    expect(text).toMatch(/\b0?4:00\b/);
    expect(text.endsWith(" UTC")).toBe(true);
  });

  it("converts to the zone rather than the browser's", () => {
    const text = formatInZone("2026-10-06T18:00:00+00:00", "Australia/Brisbane");
    expect(text).toMatch(/\b0?4:00\b/);
    expect(text).toContain("Australia/Brisbane");
  });

  it("renders a host zone cobble could only name by offset", () => {
    expect(formatInZone("2026-10-07T04:00:00+00:00", "+10:00")).toMatch(/\b0?2:00\b/);
  });

  it("handles missing and unparseable values", () => {
    expect(formatInZone(null, "UTC")).toBe("—");
    expect(formatInZone("not a date", "UTC")).toBe("not a date");
  });
});

describe("zonesMatch (design D6)", () => {
  it("Australia/Brisbane against UTC is a mismatch", () => {
    expect(zonesMatch("Australia/Brisbane", "UTC")).toBe(false);
  });

  it("Australia/Melbourne against Australia/Sydney is not", () => {
    expect(zonesMatch("Australia/Melbourne", "Australia/Sydney")).toBe(true);
  });

  it("an alias of the same zone is not", () => {
    expect(zonesMatch("Australia/Brisbane", "Australia/Queensland")).toBe(true);
  });

  it("Sydney against Brisbane is a mismatch even when sampled in July", () => {
    // Their offsets are equal in July, but differ during Sydney's summer time.
    expect(
      zonesMatch("Australia/Sydney", "Australia/Brisbane", new Date("2026-07-01")),
    ).toBe(false);
  });

  it("a fixed-offset host zone compares by its offset", () => {
    expect(zonesMatch("UTC", "+00:00")).toBe(true);
    expect(zonesMatch("Australia/Brisbane", "+00:00")).toBe(false);
  });

  it("an unresolvable zone is not a match", () => {
    expect(zonesMatch("Mars/Base", "UTC")).toBe(false);
  });
});

describe("mismatch dismissal", () => {
  it("is remembered per pair of zones", () => {
    window.localStorage.clear();
    expect(isMismatchDismissed("Australia/Brisbane", "UTC")).toBe(false);
    dismissMismatch("Australia/Brisbane", "UTC");
    expect(isMismatchDismissed("Australia/Brisbane", "UTC")).toBe(true);
    expect(isMismatchDismissed("Australia/Brisbane", "Europe/London")).toBe(false);
    expect(isMismatchDismissed("Asia/Tokyo", "UTC")).toBe(false);
  });
});
