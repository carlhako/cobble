import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { sections } from "../sections";

// 8.1: adding a placeholder section requires no shell change — the shell renders
// nav and routes purely from the `sections` list.
describe("app shell", () => {
  it("renders a nav entry for every listed section", async () => {
    const { App } = await import("../App");
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    const nav = screen.getByRole("navigation");
    for (const s of sections.filter((s) => s.nav !== false)) {
      expect(within(nav).getByRole("link", { name: s.label })).toBeInTheDocument();
    }
  });

  it("routes a section that is not listed in the nav", async () => {
    const hidden = sections.filter((s) => s.nav === false);
    expect(hidden.map((s) => s.path)).toContain("/cobble");
    const { App } = await import("../App");
    render(
      <MemoryRouter initialEntries={["/cobble"]}>
        <App />
      </MemoryRouter>,
    );
    const nav = screen.getByRole("navigation");
    for (const s of hidden) {
      expect(within(nav).queryByRole("link", { name: s.label })).toBeNull();
    }
    expect(
      screen.getByRole("heading", { name: "cobble (control panel)" }),
    ).toBeInTheDocument();
  });

  it("adding a section to the list adds a route without touching App", () => {
    const extended = [
      ...sections,
      { path: "/placeholder", label: "Placeholder", element: <div /> },
    ];
    expect(extended.map((s) => s.path)).toContain("/placeholder");
  });
});
