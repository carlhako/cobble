"""cobble-self-update 5.1: the root upgrade helper, run unprivileged against a
fake GitHub release server with a stub installer."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "deploy" / "cobble-upgrade"

STUB_INSTALLER = b"""#!/bin/bash
set -e
echo "installing $RELEASE_TAG from $COBBLE_REPO"
test -f "$COBBLE_TARBALL"
echo "tarball ok"
"""


@dataclass
class FakeRelease:
    port: int = 0
    tag: str = "v0.5.0"
    files: dict[str, bytes] = field(
        default_factory=lambda: {"install.sh": STUB_INSTALLER, "cobble.tar.gz": b"TARBALL"}
    )
    digests: dict[str, str | None] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def digest(self, name: str) -> str | None:
        if name in self.digests:
            return self.digests[name]
        return "sha256:" + hashlib.sha256(self.files[name]).hexdigest()


@pytest.fixture
def release() -> Iterator[FakeRelease]:
    state = FakeRelease()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            state.requests.append(self.path)
            if self.path == f"/repos/carlhako/cobble/releases/tags/{state.tag}":
                assets = []
                for name in state.files:
                    asset = {
                        "name": name,
                        "browser_download_url": f"{state.base}/dl/{name}",
                    }
                    d = state.digest(name)
                    if d is not None:
                        asset["digest"] = d
                    assets.append(asset)
                self._send(
                    json.dumps({"tag_name": state.tag, "assets": assets}).encode(),
                    "application/json",
                )
            elif self.path.startswith("/dl/") and self.path[4:] in state.files:
                self._send(state.files[self.path[4:]], "application/octet-stream")
            else:
                self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


@dataclass
class Dirs:
    request: Path
    status: Path

    @property
    def request_file(self) -> Path:
        return self.request / "request.json"

    @property
    def processing_file(self) -> Path:
        return self.request / "request.processing"

    def status_json(self) -> dict:
        return json.loads((self.status / "status.json").read_text())


@pytest.fixture
def dirs(tmp_path: Path) -> Dirs:
    d = Dirs(request=tmp_path / "upgrade", status=tmp_path / "cobble-upgrade")
    d.request.mkdir()
    d.status.mkdir()
    return d


def run_helper(dirs: Dirs, release: FakeRelease) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "COBBLE_UPGRADE_REQUEST_DIR": str(dirs.request),
        "COBBLE_UPGRADE_STATUS_DIR": str(dirs.status),
        "COBBLE_UPGRADE_API_URL": release.base,
    }
    return subprocess.run(
        [sys.executable, str(HELPER)], env=env, capture_output=True, text=True, timeout=60
    )


REQUEST_ID = "0123456789abcdef0123456789abcdef"


def request(dirs: Dirs, tag: str = "v0.5.0", request_id: str | None = REQUEST_ID) -> None:
    body: dict = {"tag": tag}
    if request_id is not None:
        body["request_id"] = request_id
    dirs.request_file.write_text(json.dumps(body))


def test_success_runs_the_verified_installer(dirs: Dirs, release: FakeRelease) -> None:
    request(dirs)
    proc = run_helper(dirs, release)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    st = dirs.status_json()
    assert st["tag"] == "v0.5.0" and st["state"] == "succeeded" and st["exit_code"] == 0
    assert st["request_id"] == REQUEST_ID
    assert "installing v0.5.0 from carlhako/cobble" in st["log_tail"]
    assert "tarball ok" in st["log_tail"]
    assert not dirs.request_file.exists() and not dirs.processing_file.exists()
    assert oct((dirs.status / "status.json").stat().st_mode & 0o777) == "0o644"


def test_log_tail_has_no_terminal_colour_codes(dirs: Dirs, release: FakeRelease) -> None:
    release.files["install.sh"] = b"#!/bin/bash\nprintf '\\033[1;32m==>\\033[0m done\\n'\n"
    request(dirs)
    proc = run_helper(dirs, release)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert dirs.status_json()["log_tail"] == "==> done"


def test_no_request_does_nothing(dirs: Dirs, release: FakeRelease) -> None:
    proc = run_helper(dirs, release)
    assert proc.returncode == 0
    assert not (dirs.status / "status.json").exists()
    assert release.requests == []


@pytest.mark.parametrize(
    "tag", ["latest", "v0.5", "v0.5.0; rm -rf /", "../../evil", "v12345.0.0", "", "v0.5.0\n"]
)
def test_malformed_tag_is_rejected_without_downloading(
    dirs: Dirs, release: FakeRelease, tag: str
) -> None:
    request(dirs, tag)
    proc = run_helper(dirs, release)
    assert proc.returncode == 1
    st = dirs.status_json()
    assert st["state"] == "rejected" and st["tag"] is None
    # The id still identifies the rejected request to cobble.
    assert st["request_id"] == REQUEST_ID
    assert release.requests == []
    assert not dirs.processing_file.exists()


@pytest.mark.parametrize("request_id", [None, "", "ABC", "0" * 31, "0" * 32 + "\n", "../x"])
def test_request_without_a_well_formed_id_is_rejected(
    dirs: Dirs, release: FakeRelease, request_id: str | None
) -> None:
    request(dirs, request_id=request_id)
    proc = run_helper(dirs, release)
    assert proc.returncode == 1
    st = dirs.status_json()
    assert st["state"] == "rejected" and st["request_id"] is None
    assert "request id" in st["error"]
    assert release.requests == []


def test_symlinked_request_is_rejected_and_its_target_untouched(
    dirs: Dirs, release: FakeRelease, tmp_path: Path
) -> None:
    target = tmp_path / "precious"
    target.write_text(json.dumps({"tag": "v0.5.0"}))
    dirs.request_file.symlink_to(target)
    proc = run_helper(dirs, release)
    assert proc.returncode == 1
    assert dirs.status_json()["state"] == "rejected"
    assert release.requests == []
    assert target.read_text() == json.dumps({"tag": "v0.5.0"})
    assert not os.path.lexists(dirs.processing_file)


def test_oversize_request_is_rejected(dirs: Dirs, release: FakeRelease) -> None:
    dirs.request_file.write_text(json.dumps({"tag": "v0.5.0", "pad": "x" * 5000}))
    proc = run_helper(dirs, release)
    assert proc.returncode == 1
    st = dirs.status_json()
    assert st["state"] == "rejected" and "larger" in st["error"]
    assert release.requests == []


def test_directory_planted_at_processing_path_is_rejected(dirs: Dirs, release: FakeRelease) -> None:
    dirs.processing_file.mkdir()
    (dirs.processing_file / "keep").write_text("x")
    request(dirs)
    proc = run_helper(dirs, release)
    assert proc.returncode == 1
    assert dirs.status_json()["state"] == "rejected"
    assert (dirs.processing_file / "keep").exists()


def test_missing_digest_fails_closed(dirs: Dirs, release: FakeRelease) -> None:
    release.digests["cobble.tar.gz"] = None
    request(dirs)
    proc = run_helper(dirs, release)
    assert proc.returncode == 1
    st = dirs.status_json()
    assert st["state"] == "failed" and st["tag"] == "v0.5.0"
    assert st["request_id"] == REQUEST_ID
    assert "no published sha256 digest" in st["error"]
    assert not any(r.startswith("/dl/") for r in release.requests)


def test_mismatched_digest_fails_before_running_anything(dirs: Dirs, release: FakeRelease) -> None:
    release.digests["install.sh"] = "sha256:" + "0" * 64
    request(dirs)
    proc = run_helper(dirs, release)
    assert proc.returncode == 1
    st = dirs.status_json()
    assert st["state"] == "failed"
    assert "install.sh does not match its published sha256 digest" in st["error"]
    assert "installing" not in (st["log_tail"] or "")


def test_missing_asset_fails(dirs: Dirs, release: FakeRelease) -> None:
    del release.files["cobble.tar.gz"]
    request(dirs)
    run_helper(dirs, release)
    st = dirs.status_json()
    assert st["state"] == "failed" and "missing cobble.tar.gz" in st["error"]


def test_unknown_release_fails(dirs: Dirs, release: FakeRelease) -> None:
    request(dirs, "v9.9.9")
    run_helper(dirs, release)
    st = dirs.status_json()
    assert st["state"] == "failed" and "HTTP 404" in st["error"]


def test_installer_failure_is_recorded_with_its_output(dirs: Dirs, release: FakeRelease) -> None:
    release.files["install.sh"] = b"#!/bin/bash\necho 'apt is broken' >&2\nexit 3\n"
    request(dirs)
    proc = run_helper(dirs, release)
    assert proc.returncode == 1
    st = dirs.status_json()
    assert st["state"] == "failed"
    assert st["error"] == "the installer exited with status 3"
    assert "apt is broken" in st["log_tail"]
    assert not dirs.processing_file.exists()


def test_repo_line_is_rewritable_by_the_installer() -> None:
    # install.sh bakes its REPO in with sed on exactly this line.
    lines = [ln for ln in HELPER.read_text().splitlines() if ln.startswith("REPO = ")]
    assert lines == ['REPO = "carlhako/cobble"']
