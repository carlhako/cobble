import { Link, NavLink, Route, Routes } from "react-router-dom";
import { sections } from "./sections";
import { ConnectionBanner } from "./components/ConnectionBanner";
import { StatusProvider, useStatus } from "./api/StatusContext";
import { CobbleVersionProvider, useCobbleVersion } from "./api/useCobbleVersion";
import { CobbleSettingsProvider } from "./api/useCobbleSettings";

/** `[0.4.0]` beside the brand: green when current, orange when a newer
 *  release exists, muted when availability is unknown. In every state it opens
 *  the cobble page (web-ui-shell: the cobble version and its update state). */
function VersionBadge() {
  const { info } = useCobbleVersion();
  if (!info) return null;
  if (info.update_available) {
    return (
      <Link
        to="/cobble"
        className="version-badge is-update"
        title={`cobble ${info.latest} is available`}
      >
        [{info.current} update available]
      </Link>
    );
  }
  // A failed check keeps the last successful result, which still answers
  // whether this install is current (cobble-self-update).
  const known = info.latest !== null;
  return (
    <Link
      to="/cobble"
      className={`version-badge${known ? " is-current" : ""}`}
      title={known ? "cobble is up to date" : "update availability unknown"}
    >
      [{info.current}]
    </Link>
  );
}

/** A cog at the right of the header's top row that opens the cobble page: a
 *  second way in beside the version badge (web-ui-shell: the settings cog). */
function SettingsCog() {
  return (
    <NavLink
      to="/cobble"
      className="settings-cog"
      aria-label="cobble settings"
      title="cobble settings"
    >
      <svg
        viewBox="0 0 24 24"
        width="18"
        height="18"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    </NavLink>
  );
}

/** While a cobble upgrade is in flight the page will lose its connection and
 *  then reload itself onto the new version. */
function UpgradeBanner() {
  const { info } = useCobbleVersion();
  const u = info?.upgrade;
  if (!u || (u.state !== "pending" && u.state !== "running")) return null;
  return (
    <div className="upgrade-banner" role="status">
      Upgrading cobble to {u.to}. The server is stopped until the new version starts, and
      this page reloads by itself when it's back.
    </div>
  );
}

function Shell() {
  const { connected } = useStatus();
  return (
    <div className="app">
      <header className="app-header">
        <span className="brand-group">
          <span className="brand">cobble</span>
          <VersionBadge />
        </span>
        <nav className="app-nav">
          {sections
            .filter((s) => s.nav !== false)
            .map((s) => (
              <NavLink key={s.path} to={s.path} end={s.path === "/"}>
                {s.label}
              </NavLink>
            ))}
        </nav>
        <SettingsCog />
      </header>
      <UpgradeBanner />
      <ConnectionBanner connected={connected} />
      <main className="app-main">
        <Routes>
          {sections.map((s) => (
            <Route key={s.path} path={s.path} element={s.element} />
          ))}
        </Routes>
      </main>
    </div>
  );
}

export function App() {
  return (
    <StatusProvider>
      <CobbleVersionProvider>
        <CobbleSettingsProvider>
          <Shell />
        </CobbleSettingsProvider>
      </CobbleVersionProvider>
    </StatusProvider>
  );
}
