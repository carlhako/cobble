import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { sections } from "../sections";

// 8.1: adding a placeholder section requires no shell change — the shell renders
// nav and routes purely from the `sections` list.
describe("app shell", () => {
  it("renders a nav entry for every registered section", async () => {
    const { App } = await import("../App");
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    for (const s of sections) {
      expect(screen.getByRole("link", { name: s.label })).toBeInTheDocument();
    }
  });

  it("adding a section to the list adds a route without touching App", () => {
    const extended = [
      ...sections,
      { path: "/placeholder", label: "Placeholder", element: <div /> },
    ];
    expect(extended.map((s) => s.path)).toContain("/placeholder");
  });
});
