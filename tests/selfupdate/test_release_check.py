"""cobble-self-update 2.2: the release checker against a mock GitHub."""

from __future__ import annotations

import json

import httpx
import pytest

from cobble.selfupdate.release_check import ReleaseChecker
from cobble.settings import Settings


def _release(tag: str = "v0.5.0", **extra) -> dict:
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/carlhako/cobble/releases/tag/{tag}",
        "draft": False,
        "prerelease": False,
        **extra,
    }


class FakeGitHub:
    """A scripted ``httpx.MockTransport``: each request pops the next response."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def _ok(body: dict, etag: str = '"abc"') -> httpx.Response:
    return httpx.Response(200, json=body, headers={"ETag": etag})


@pytest.fixture
def settings(tmp_settings: Settings) -> Settings:
    return tmp_settings.model_copy(update={"release_api_url": "https://api.test"})


def _checker(settings: Settings, gh: FakeGitHub, current: str = "0.4.0") -> ReleaseChecker:
    return ReleaseChecker(settings, current=current, transport=gh.transport, now=lambda: "T")


def test_200_newer_release_is_reported_available(settings: Settings) -> None:
    gh = FakeGitHub(_ok(_release("v0.5.0")))
    c = _checker(settings, gh)
    c.check_now()
    view = c.view()
    assert view == {
        "current": "0.4.0",
        "latest": "0.5.0",
        "update_available": True,
        "release_url": "https://github.com/carlhako/cobble/releases/tag/v0.5.0",
        "release_name": None,
        "published_at": None,
        "notes": None,
        "checked_at": "T",
        "check_error": None,
    }
    req = gh.requests[0]
    assert req.url == "https://api.test/repos/carlhako/cobble/releases/latest"
    assert req.headers["User-Agent"] == settings.user_agent
    assert "If-None-Match" not in req.headers


def test_200_same_version_is_not_available(settings: Settings) -> None:
    c = _checker(settings, FakeGitHub(_ok(_release("v0.4.0"))))
    c.check_now()
    assert c.update_available() is False


def test_dev_build_newer_than_latest_is_not_available(settings: Settings) -> None:
    c = _checker(settings, FakeGitHub(_ok(_release("v0.4.0"))), current="0.5.0")
    c.check_now()
    assert c.update_available() is False


def test_prerelease_is_never_an_update(settings: Settings) -> None:
    c = _checker(settings, FakeGitHub(_ok(_release("v0.9.0", prerelease=True))))
    c.check_now()
    assert c.update_available() is None
    assert c.view()["update_available"] is False
    assert "pre-release" in c.state.check_error


def test_304_keeps_the_cached_result_and_sends_the_etag(settings: Settings) -> None:
    gh = FakeGitHub(_ok(_release("v0.5.0"), etag='"e1"'), httpx.Response(304))
    c = _checker(settings, gh)
    c.check_now()
    c.check_now()
    assert gh.requests[1].headers["If-None-Match"] == '"e1"'
    assert c.state.latest == "0.5.0"
    assert c.state.check_error is None


@pytest.mark.parametrize("status", [403, 429])
def test_rate_limit_is_unknown_not_fatal(settings: Settings, status: int) -> None:
    c = _checker(settings, FakeGitHub(httpx.Response(status)))
    c.check_now()
    assert c.update_available() is None
    assert f"HTTP {status}" in c.state.check_error


def test_404_no_release_is_unknown(settings: Settings) -> None:
    c = _checker(settings, FakeGitHub(httpx.Response(404)))
    c.check_now()
    assert c.update_available() is None
    assert c.state.check_error == "no published release was found"


def test_timeout_keeps_the_last_good_result(settings: Settings) -> None:
    gh = FakeGitHub(_ok(_release("v0.5.0")), httpx.ConnectTimeout("timed out"))
    c = _checker(settings, gh)
    c.check_now()
    c.check_now()
    assert c.state.latest == "0.5.0"
    assert c.update_available() is True
    assert c.state.check_error.startswith("release source unreachable")


def test_unusable_body_is_an_error(settings: Settings) -> None:
    c = _checker(settings, FakeGitHub(httpx.Response(200, content=b"not json")))
    c.check_now()
    assert c.update_available() is None
    assert "unusable" in c.state.check_error


def test_result_survives_a_restart(settings: Settings) -> None:
    c = _checker(settings, FakeGitHub(_ok(_release("v0.5.0"))))
    c.check_now()
    stored = json.loads((settings.state_dir / "release_check.json").read_text())
    assert stored["latest"] == "0.5.0"

    reloaded = ReleaseChecker(settings, current="0.4.0", transport=FakeGitHub().transport)
    assert reloaded.update_available() is True
    assert reloaded.view()["release_url"].endswith("/v0.5.0")


def test_corrupt_cache_file_is_ignored(settings: Settings) -> None:
    (settings.state_dir / "release_check.json").write_text("{nope")
    c = ReleaseChecker(settings, current="0.4.0", transport=FakeGitHub().transport)
    assert c.update_available() is None


def test_notes_title_and_date_are_reported(settings: Settings) -> None:
    rel = _release(
        "v0.5.0",
        name="cobble 0.5.0",
        published_at="2026-09-24T00:17:27Z",
        body="## What's new\n\n- things\n",
    )
    c = _checker(settings, FakeGitHub(_ok(rel)))
    c.check_now()
    view = c.view()
    assert view["release_name"] == "cobble 0.5.0"
    assert view["published_at"] == "2026-09-24T00:17:27Z"
    assert view["notes"] == "## What's new\n\n- things"


def test_notes_are_reported_when_already_current(settings: Settings) -> None:
    c = _checker(settings, FakeGitHub(_ok(_release("v0.4.0", body="- fixed"))))
    c.check_now()
    assert c.update_available() is False
    assert c.view()["notes"] == "- fixed"


@pytest.mark.parametrize("body", ["", "  \n\t ", None])
def test_empty_notes_are_absent(settings: Settings, body: str | None) -> None:
    c = _checker(settings, FakeGitHub(_ok(_release("v0.5.0", body=body, name=""))))
    c.check_now()
    assert c.update_available() is True
    assert c.view()["notes"] is None
    assert c.view()["release_name"] is None


def test_state_without_schema_is_fetched_in_full(settings: Settings) -> None:
    # What a v0.5.x cobble persisted: a result and an ETag, but no notes.
    (settings.state_dir / "release_check.json").write_text(
        json.dumps(
            {
                "latest": "0.5.0",
                "tag": "v0.5.0",
                "release_url": "https://github.com/carlhako/cobble/releases/tag/v0.5.0",
                "etag": '"old"',
                "checked_at": "T0",
                "check_error": None,
            }
        )
    )
    gh = FakeGitHub(_ok(_release("v0.5.0", body="- notes"), etag='"new"'))
    c = _checker(settings, gh)
    assert c.update_available() is True  # the old result is still served
    c.check_now()
    assert "If-None-Match" not in gh.requests[0].headers
    assert c.view()["notes"] == "- notes"
    stored = json.loads((settings.state_dir / "release_check.json").read_text())
    assert stored["schema"] == 2
    assert stored["notes"] == "- notes"


def test_current_schema_keeps_its_etag_across_a_restart(settings: Settings) -> None:
    _checker(settings, FakeGitHub(_ok(_release("v0.5.0"), etag='"e1"'))).check_now()
    gh = FakeGitHub(httpx.Response(304))
    _checker(settings, gh).check_now()
    assert gh.requests[0].headers["If-None-Match"] == '"e1"'
