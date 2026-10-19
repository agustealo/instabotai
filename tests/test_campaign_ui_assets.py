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
        setup_script = await client.get("/assets/setup.js")
        setup_stylesheet = await client.get("/assets/setup.css")

    assert index.status_code == 200
    assert "AI Studio" in index.text
    assert loader.status_code == 200
    assert "/assets/app-core.js" in loader.text
    assert "/assets/campaigns-shell.js" in loader.text
    assert "/assets/setup.js" in loader.text
    assert "__instabotaiDomReady" in loader.text
    assert core.status_code == 200
    assert "function initialize()" in core.text
    assert "function confirmConsumerAction(" in core.text
    assert 'state.worker = await api("/api/worker")' in core.text
    assert 'kind !== "error"' in core.text
    assert "Array.isArray(body.detail)" in core.text

    assert shell.status_code == 200
    assert 'button.dataset.view = "campaigns"' in shell.text
    assert 'section.id = "view-campaigns"' in shell.text
    assert "Campaign planning and provider execution are deliberately separate" in shell.text
    assert "/assets/trial-evidence.js" in shell.text
    assert "export its secret-free evidence" in shell.text

    assert script.status_code == 200
    assert "function canExecuteJob(job)" in script.text
    assert "if (!state.runtime || !state.runtime.policy) return false" in script.text
    assert "confirmJobChange(job, \"Execute\", true)" in script.text
    assert "confirmCampaignChange(campaign, \"Archive\", true)" in script.text
    assert "pending_approval" in script.text
    assert "/api/campaign-jobs/" in script.text
    assert "Business outcome recorded" in script.text

    assert evidence.status_code == 200
    assert "Export evidence" in evidence.text
    assert "/evidence`" in evidence.text
    assert "application/json" in evidence.text
    assert "SHA-256 integrity metadata" in evidence.text

    assert setup_script.status_code == 200
    assert 'api("/api/consumer")' in setup_script.text
    assert 'api("/api/runtime")' in setup_script.text
    assert 'document.querySelector("#view-overview .hero [data-go]")' in setup_script.text
    assert 'api("/api/readiness/probe"' in setup_script.text
    assert "Credentials are configured on your machine" in setup_script.text
    assert setup_stylesheet.status_code == 200
    assert ".setup-progress" in setup_stylesheet.text

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
        "setup.js",
    ):
        result = subprocess.run(
            [node, "--check", str(static_dir / asset)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{asset}: {result.stderr}"
