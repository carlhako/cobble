"""Task 9.1: the release tarball carries the pre-built bundle and no frontend
source. Runs the same staging + guard the GitHub Actions workflow does.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _build_frontend() -> None:
    subprocess.run(
        ["npm", "--prefix", "web", "run", "build"],
        cwd=REPO,
        check=True,
        capture_output=True,
        timeout=300,
    )


@pytest.mark.skipif(
    not (REPO / "web" / "node_modules").is_dir(),
    reason="frontend deps not installed",
)
def test_tarball_has_bundle_and_no_frontend_source(tmp_path: Path) -> None:
    _build_frontend()
    assert (REPO / "src" / "cobble" / "static" / "index.html").is_file()

    stage = tmp_path / "cobble"
    stage.mkdir()
    for item in ("src", "pyproject.toml", "README.md", "deploy"):
        subprocess.run(["cp", "-a", str(REPO / item), str(stage)], check=True)

    tarball = tmp_path / "cobble.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(stage, arcname="cobble")

    with tarfile.open(tarball) as tf:
        names = tf.getnames()

    # the pre-built interface is present
    assert any(n.endswith("src/cobble/static/index.html") for n in names)
    assert any("/static/assets/" in n and n.endswith(".js") for n in names)

    # no frontend source of any kind
    for n in names:
        assert "/web/" not in n, f"frontend dir leaked: {n}"
        assert not n.endswith((".tsx", ".ts")) or n.endswith(".d.ts"), f"TS source leaked: {n}"
        assert not n.endswith("vite.config.ts")
        assert "node_modules" not in n

    # python source and deploy assets are present
    assert any(n.endswith("src/cobble/__main__.py") for n in names)
    assert any(n.endswith("deploy/cobble.service") for n in names)
    assert any(n.endswith("deploy/install.sh") for n in names)


def test_install_script_and_unit_are_syntactically_valid() -> None:
    r = subprocess.run(
        ["bash", "-n", str(REPO / "deploy" / "install.sh")],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr

    unit = (REPO / "deploy" / "cobble.service").read_text()
    # TimeoutStopSec must exceed the default Bedrock shutdown timeout (120s).
    line = next(x for x in unit.splitlines() if x.startswith("TimeoutStopSec="))
    assert int(line.split("=")[1]) > 120
    assert "Restart=on-failure" in unit
    assert "KillSignal=SIGTERM" in unit


def test_workflow_builds_frontend_and_guards_against_source_leak() -> None:
    wf = (REPO / ".github" / "workflows" / "release.yml").read_text()
    assert "npm --prefix web run build" in wf
    assert "src/cobble/static/index.html" in wf
    assert "frontend source leaked" in wf  # the guard exists
    assert "wheelhouse" in wf  # deps vendored, no compiler on host


if sys.platform != "linux":  # pragma: no cover
    pytest.skip("linux-only deploy assets", allow_module_level=True)
