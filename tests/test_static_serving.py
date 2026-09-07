"""Section 1.3: serve the built frontend with client-side-route fallback."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cobble.app import create_app
from cobble.settings import Settings
from cobble.staticfiles import frontend_built


@pytest.mark.skipif(not frontend_built(), reason="frontend bundle not built")
def test_nested_interface_route_returns_the_interface(tmp_settings: Settings) -> None:
    app = create_app(tmp_settings)
    with TestClient(app) as client:
        index = client.get("/")
        nested = client.get("/console")
    assert index.status_code == 200
    assert nested.status_code == 200
    # A direct request to a nested client-side route returns index.html, not 404.
    assert nested.text == index.text
    assert '<div id="root">' in nested.text


@pytest.mark.skipif(not frontend_built(), reason="frontend bundle not built")
def test_real_built_asset_is_served_verbatim(tmp_settings: Settings) -> None:
    from cobble.staticfiles import static_dir

    asset = next((static_dir() / "assets").glob("*.js"))
    rel = f"/assets/{asset.name}"
    app = create_app(tmp_settings)
    with TestClient(app) as client:
        resp = client.get(rel)
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert resp.text == asset.read_text()


def test_unknown_api_route_is_404_not_index(tmp_settings: Settings) -> None:
    app = create_app(tmp_settings)
    with TestClient(app) as client:
        resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
