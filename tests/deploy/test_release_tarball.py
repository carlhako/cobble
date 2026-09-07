"""Task 9.1: the release artifact is a cobble wheel (carrying the pre-built
web bundle) plus docs and deploy assets — no frontend source, no build backend
needed on the host. Mirrors the GitHub Actions workflow's build + guard.
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

if sys.platform != "linux":  # pragma: no cover
    pytest.skip("linux-only deploy assets", allow_module_level=True)


@pytest.mark.skipif(
    not (REPO / "web" / "node_modules").is_dir(),
    reason="frontend deps not installed",
)
def test_release_tarball_is_wheel_plus_assets_no_frontend_source(tmp_path: Path) -> None:
    subprocess.run(
        ["npm", "--prefix", "web", "run", "build"],
        cwd=REPO,
        check=True,
        capture_output=True,
        timeout=300,
    )
    assert (REPO / "src" / "cobble" / "static" / "index.html").is_file()

    dist = tmp_path / "dist"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist)],
        cwd=REPO,
        check=True,
        capture_output=True,
        timeout=300,
    )
    wheel = next(dist.glob("cobble-*-py3-none-any.whl"))

    # The wheel carries the built interface (force-include in pyproject.toml).
    wheel_names = zipfile.ZipFile(wheel).namelist()
    assert "cobble/static/index.html" in wheel_names
    assert any(n.startswith("cobble/static/assets/") for n in wheel_names)
    assert "cobble/__main__.py" in wheel_names
    assert not any(n.endswith((".tsx", ".ts")) for n in wheel_names)

    # Stage + tar exactly as the workflow does.
    stage = tmp_path / "cobble"
    stage.mkdir()
    subprocess.run(["cp", "-a", str(dist), str(stage / "dist")], check=True)
    for item in ("README.md", "deploy"):
        subprocess.run(["cp", "-a", str(REPO / item), str(stage)], check=True)

    tarball = tmp_path / "cobble.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(stage, arcname="cobble")
    names = tarfile.open(tarball).getnames()

    assert any(n.endswith(".whl") and "/dist/cobble-" in n for n in names)
    assert any(n.endswith("deploy/cobble.service") for n in names)
    assert any(n.endswith("deploy/install.sh") for n in names)
    for n in names:
        assert "/web/" not in n, f"frontend dir leaked: {n}"
        assert not n.endswith((".tsx", ".ts")), f"TS source leaked: {n}"
        assert "node_modules" not in n
        assert not n.endswith("/src/cobble/__main__.py"), "raw python source should not ship"


def test_install_script_and_unit_are_valid() -> None:
    r = subprocess.run(
        ["bash", "-n", str(REPO / "deploy" / "install.sh")],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr

    script = (REPO / "deploy" / "install.sh").read_text()
    # No-compiler guarantee and safe wheel install.
    assert "--only-binary=:all:" in script
    assert '"$wheel"' in script  # installs the bundled wheel by path, not by bare name

    unit = (REPO / "deploy" / "cobble.service").read_text()
    line = next(x for x in unit.splitlines() if x.startswith("TimeoutStopSec="))
    assert int(line.split("=")[1]) > 120  # must exceed the 120s BDS shutdown timeout
    assert "Restart=on-failure" in unit
    assert "KillSignal=SIGTERM" in unit


def test_workflow_builds_frontend_and_guards_against_source_leak() -> None:
    wf = (REPO / ".github" / "workflows" / "release.yml").read_text()
    assert "npm --prefix web run build" in wf
    assert "python -m build --wheel" in wf
    assert "frontend source leaked" in wf
    assert "missing the built frontend" in wf  # wheel-content sanity check
