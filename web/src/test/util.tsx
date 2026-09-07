import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { StatusProvider } from "../api/StatusContext";

export function renderApp(ui: ReactElement) {
  return render(
    <MemoryRouter>
      <StatusProvider>{ui}</StatusProvider>
    </MemoryRouter>,
  );
}
