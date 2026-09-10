import type { ReactElement } from "react";
import { Dashboard } from "./sections/Dashboard";
import { Console } from "./sections/Console";
import { UpdatesBackups } from "./sections/UpdatesBackups";
import { Configuration } from "./sections/Configuration";
import { Gamerules } from "./sections/Gamerules";
import { Players } from "./sections/Players";
import { ImportWorld } from "./sections/ImportWorld";

export interface Section {
  path: string;
  label: string;
  element: ReactElement;
}

// The shell renders navigation and routes from this list. Adding a screen in
// later milestones (configuration, gamerules, players) is one entry here and
// requires no change to App.tsx (web-ui-shell: "a new section is added").
export const sections: Section[] = [
  { path: "/", label: "Dashboard", element: <Dashboard /> },
  { path: "/console", label: "Console", element: <Console /> },
  { path: "/updates", label: "Updates & Backups", element: <UpdatesBackups /> },
  { path: "/configuration", label: "Configuration", element: <Configuration /> },
  { path: "/gamerules", label: "Gamerules", element: <Gamerules /> },
  { path: "/players", label: "Players", element: <Players /> },
  { path: "/import", label: "Import World", element: <ImportWorld /> },
];
