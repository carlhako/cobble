"""Resolve the current Bedrock Dedicated Server version from the vendor source.

The vendor exposes a JSON endpoint listing current download URLs (design.md —
Acquisition). No HTML scraping is involved. Every request carries a User-Agent;
the vendor rejects requests without one, so the header is set centrally on the
client and a request is never issued without it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from cobble.logging import get_logger
from cobble.settings import Settings

log = get_logger("acquisition.version")

_LINUX_DOWNLOAD_TYPE = "serverBedrockLinux"
# bedrock-server-1.26.45.1.zip -> 1.26.45.1
_VERSION_RE = re.compile(r"bedrock-server-([0-9]+(?:\.[0-9]+)+)\.zip$")


class VersionResolutionError(RuntimeError):
    """The vendor source was unreachable or its response could not be used.

    Callers surface and log this; they never let it escape as an unhandled
    exception, and an already-installed server keeps running.
    """


@dataclass(frozen=True)
class ResolvedVersion:
    version: str
    download_url: str


def _client(settings: Settings) -> httpx.Client:
    # User-Agent is attached to the client, so it is present on every request
    # including redirected downloads. There is no code path that issues a
    # request without it.
    return httpx.Client(
        headers={"User-Agent": settings.user_agent},
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
    )


def resolve_current_version(settings: Settings) -> ResolvedVersion:
    """Return the current Linux BDS version and its download URL.

    Raises :class:`VersionResolutionError` on any failure. The message names the
    specific problem.
    """
    url = settings.download_links_url
    try:
        with _client(settings) as client:
            resp = client.get(url)
            resp.raise_for_status()
            payload = resp.json()
    except httpx.HTTPError as exc:
        raise VersionResolutionError(f"vendor source unreachable: {exc}") from exc
    except ValueError as exc:  # JSON decode
        raise VersionResolutionError(f"vendor source returned non-JSON: {exc}") from exc

    try:
        links = payload["result"]["links"]
    except (KeyError, TypeError) as exc:
        raise VersionResolutionError("vendor response missing 'result.links'") from exc

    download_url: str | None = None
    for entry in links:
        if isinstance(entry, dict) and entry.get("downloadType") == _LINUX_DOWNLOAD_TYPE:
            download_url = entry.get("downloadUrl")
            break
    if not download_url:
        raise VersionResolutionError(
            f"vendor response has no '{_LINUX_DOWNLOAD_TYPE}' download link"
        )

    match = _VERSION_RE.search(download_url)
    if not match:
        raise VersionResolutionError(
            f"could not parse a version from download URL {download_url!r}"
        )
    return ResolvedVersion(version=match.group(1), download_url=download_url)


def try_resolve_current_version(settings: Settings) -> ResolvedVersion | None:
    """Non-raising wrapper: log the failure and return ``None``.

    Used by callers for whom a failed version check must be a surfaced non-event
    that never blocks startup or stops a running server.
    """
    try:
        return resolve_current_version(settings)
    except VersionResolutionError as exc:
        log.warning("version resolution failed: %s", exc)
        return None
