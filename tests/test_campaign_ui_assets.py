"""Consumer campaign workspace asset and shell regressions."""

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from instabotai.settings import Settings
from instabotai.web import create_app


async def test_campaign_workspace_is_shipped_as_local_consumer_assets() -> None:
    settings = Settings(state_db_path=":memory:", ui_open_browser=False)
    transport = httpx.ASGITransport(app=create_app(settings=settings))

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        index = await client.get("/")
        loader = await client.get("/assets/app.js")
        core = await client.get("/assets/app-core.js")
        shell = await client.get("/assets/campaigns-shell.js")
        script = await client.get("/assets/campaigns.js")
        evidence = await client.get("/assets/trial-evidence.js")
        stylesheet = await client.get("/assets/campaigns.css")

    assert index.status_code == 200
    assert "AI Studio" in index.text
    assert loader.status_code == 200
    assert "/assets/app-core.js" in loader.text
    assert "/assets/campaigns-shell.js" in loader.text
    assert "__instabotaiDomReady" in loader.text
    assert core.status_code == 200
    assert "function initialize()" in core.text

    assert shell.status_code == 200
    assert 'button.dataset.view = "campaigns"' in shell.text
    assert 'section.id = "view-campaigns"' in shell.text
    assert "Campaign planning and provider execution are deliberately separate" in shell.text
    assert "/assets/trial-evidence.js" in shell.text
    assert "export its secret-free evidence" in shell.text

    assert script.status_code == 200
    assert "pending_approval" in script.text
    assert "/api/campaign-jobs/" in script.text
    assert "Business outcome recorded" in script.text

    assert evidence.status_code == 200
    assert "Export evidence" in evidence.text
    assert "/evidence`" in evidence.text
    assert "application/json" in evidence.text
    assert "SHA-256 integrity metadata" in evidence.text

    assert stylesheet.status_code == 200
    assert ".campaign-job-card" in stylesheet.text
    assert ".outcome-form" in stylesheet.text


def test_shipped_consumer_javascript_parses_when_node_is_available() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable in this environment")

    static_dir = Path(__file__).resolve().parents[1] / "instabotai" / "web" / "static"
    for asset in (
        "app.js",
        "app-core.js",
        "campaigns-shell.js",
        "campaigns.js",
        "trial-evidence.js",
    ):
        result = subprocess.run(
            [node, "--check", str(static_dir / asset)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{asset}: {result.stderr}"
