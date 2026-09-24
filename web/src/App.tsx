import { NavLink, Route, Routes } from "react-router-dom";
import { sections } from "./sections";
import { ConnectionBanner } from "./components/ConnectionBanner";
import { StatusProvider, useStatus } from "./api/StatusContext";
import { CobbleVersionProvider, useCobbleVersion } from "./api/useCobbleVersion";

/** `[0.4.0]` beside the brand: green when current, orange and linked to the
 *  release when a newer one exists, muted when availability is unknown
 *  (web-ui-shell: the cobble version and its update state). */
function VersionBadge() {
  const { info } = useCobbleVersion();
  if (!info) return null;
  if (info.update_available && info.release_url) {
    return (
      <a
        className="version-badge is-update"
        href={info.release_url}
        target="_blank"
        rel="noopener noreferrer"
        title={`cobble ${info.latest} is available`}
      >
        [{info.current} update available]
      </a>
    );
  }
  // A failed check keeps the last successful result, which still answers
  // whether this install is current (cobble-self-update).
  const known = info.latest !== null;
  return (
    <span
      className={`version-badge${known ? " is-current" : ""}`}
      title={known ? "cobble is up to date" : "update availability unknown"}
    >
      [{info.current}]
    </span>
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
          {sections.map((s) => (
            <NavLink key={s.path} to={s.path} end={s.path === "/"}>
              {s.label}
            </NavLink>
          ))}
        </nav>
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
        <Shell />
      </CobbleVersionProvider>
    </StatusProvider>
  );
}
