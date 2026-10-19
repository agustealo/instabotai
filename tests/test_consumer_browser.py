"""Browser-driven consumer journeys, using local state and no Instagram provider writes.

Only public research is mocked. Evidence, review, campaign persistence and UI scripts
run against the actual loopback FastAPI server and canonical SQLite implementation.
These tests are automation evidence, not a substitute for a human acceptance trial.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from collections.abc import Iterator

import pytest
import uvicorn

from instabotai.settings import Settings
from instabotai.web import create_app

playwright = pytest.importorskip("playwright.sync_api")
Browser = playwright.Browser
Page = playwright.Page
expect = playwright.expect
sync_playwright = playwright.sync_playwright


@pytest.fixture(scope="module")
def consumer_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    root = tmp_path_factory.mktemp("consumer-browser")
    settings = Settings(
        _env_file=None,
        state_db_path=str(root / "consumer-state.sqlite3"),
        ui_open_browser=False,
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    app = create_app(settings=settings)
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="error", access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(base + "/healthz", timeout=1) as response:
                    if json.load(response)["status"] == "ok":
                        break
            except (OSError, ValueError):
                time.sleep(0.1)
        else:
            raise AssertionError("Loopback consumer server did not become healthy")
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive(), "Consumer server failed to stop"


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as driver:
        instance = driver.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def page(browser: Browser, consumer_url: str) -> Iterator[Page]:
    context = browser.new_context(
        viewport={"width": 1280, "height": 850},
        reduced_motion="reduce",
    )
    window = context.new_page()
    uncaught: list[str] = []
    window.on("pageerror", lambda error: uncaught.append(str(error)))
    try:
        window.goto(consumer_url, wait_until="domcontentloaded")
        expect(window.locator('.nav-item[data-view="library"]')).to_be_visible()
        expect(window.locator("#view-campaigns")).to_be_attached()
        yield window
        assert not uncaught, f"Uncaught JavaScript errors: {uncaught}"
    finally:
        context.close()


def open_library(page: Page) -> None:
    page.locator('.nav-item[data-view="library"]').click()
    expect(page.locator("#view-library")).to_have_class("view is-active")
    expect(page.locator("#library-list")).to_be_visible()


def save_source(page: Page, title: str) -> None:
    page.locator("#library-title").fill(title)
    page.locator("#library-source").fill("https://example.org/products/verified")
    page.locator("#library-content").fill("Autumn product imagery and dates were approved.")
    page.locator("#library-tags").fill("product, launch")
    page.locator("#library-form button[type='submit']").click()
    expect(page.locator(".library-entry")).to_contain_text(title)


def test_saved_evidence_review_and_supervised_campaign_creation(
    page: Page, consumer_url: str,
) -> None:
    """The actual UI must carry evidence to a saved draft with no provider activity."""

    open_library(page)
    save_source(page, "Autumn catalog product notes")
    page.get_by_role("button", name="Mark reviewed", exact=True).click()
    dialog = page.locator("dialog[open]")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Mark reviewed").click()
    expect(page.locator(".library-entry")).to_contain_text("Reviewed")

    page.locator(".library-entry-actions").get_by_role("button", name="Edit").click()
    page.locator("#library-content").fill("Revised autumn launch notes need review.")
    page.locator("#library-save").click()
    page.locator("dialog[open]").get_by_role("button", name="Save changes").click()
    expect(page.locator(".library-entry")).to_contain_text("Unverified")

    page.locator(".library-entry-selection input").check()
    page.locator("#library-objective").fill("Introduce approved autumn products.")
    page.locator("#library-attach").click()
    page.locator("dialog[open]").get_by_role("button", name="Prepare draft").click()

    expect(page.locator("#view-campaigns")).to_have_class("view is-active")
    expect(page.locator("#campaign-mode")).to_have_value("supervised")
    expect(page.locator("#campaign-objective")).to_have_value(
        "Introduce approved autumn products."
    )
    expect(page.locator(".campaign-evidence-source").first).to_have_value(
        "https://example.org/products/verified"
    )
    assert "Revised autumn launch notes" in page.locator(
        ".campaign-evidence-content"
    ).first.input_value()

    page.locator("#campaign-create-submit").click()
    expect(page.locator("#campaign-list")).to_contain_text(
        "Introduce approved autumn products."
    )
    response = page.request.get(consumer_url + "/api/campaigns")
    assert response.ok
    campaigns = response.json()
    saved = next(
        item for item in campaigns if item["objective"] == "Introduce approved autumn products."
    )
    assert saved["status"] == "draft"
    assert saved["mode"] == "supervised"
    assert len(saved["evidence"]) == 1
    assert saved["evidence"][0]["evidence_id"].startswith("library-")

    page.reload(wait_until="domcontentloaded")
    open_library(page)
    expect(page.locator(".library-entry")).to_contain_text(
        "Autumn catalog product notes"
    )


def test_research_selection_persists_as_unverified_without_external_network(
    page: Page,
) -> None:
    """Only the research result is a fixture; saved library entries remain real."""

    report = {
        "objective": "Identify autumn audience interests.",
        "confidence": 0.87,
        "stopped_early": False,
        "blocked_urls": [],
        "failed_urls": [],
        "pages": [
            {
                "url": "https://example.org/market-report",
                "title": "Autumn trends report",
                "markdown": "The audience is interested in useful autumn product tips.",
                "relevance": 0.85,
            }
        ],
    }
    page.route(
        "**/api/research",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(report),
        ),
    )
    page.locator('.nav-item[data-view="research"]').click()
    page.locator("#research-objective").fill(report["objective"])
    page.locator("#research-seeds").fill(report["pages"][0]["url"])
    page.locator("#research-submit").click()
    expect(page.locator(".research-page")).to_have_count(1)
    page.locator(".research-pick").check()
    page.get_by_role("button", name="Save selected to library").click()
    expect(page.locator("dialog[open]")).to_be_visible()
    page.locator("dialog[open]").get_by_role(
        "button", name="Save to library"
    ).click()
    expect(page.locator("#view-library")).to_have_class("view is-active")
    expect(page.locator(".library-entry").filter(has_text="Autumn trends report")).to_be_visible()
    saved_report = page.locator(".library-entry").filter(has_text="Autumn trends report")
    expect(saved_report).to_contain_text("Unverified")


def test_stale_browser_review_is_rejected_without_overwriting(
    browser: Browser, consumer_url: str,
) -> None:
    """A second browser with an outdated version cannot update reviewed content."""

    context_a = browser.new_context()
    context_b = browser.new_context()
    try:
        a = context_a.new_page()
        b = context_b.new_page()
        created = a.request.post(
            consumer_url + "/api/evidence-library",
            data={
                "title": "Concurrency proof",
                "source": "Approved test brief",
                "content": "Initial approved text",
                "origin": "manual",
            },
        )
        assert created.status == 201, created.text()
        for page in (a, b):
            page.goto(consumer_url, wait_until="domcontentloaded")
            open_library(page)
            concurrent_entry = page.locator(".library-entry").filter(has_text="Concurrency proof")
            expect(concurrent_entry).to_be_visible()

        a.locator(".library-entry").filter(has_text="Concurrency proof").get_by_role(
            "button", name="Mark reviewed", exact=True,
        ).click()
        a.locator("dialog[open]").get_by_role("button", name="Mark reviewed").click()
        expect(a.locator(".library-entry").filter(has_text="Concurrency proof")).to_contain_text(
            "Reviewed"
        )

        b.locator(".library-entry").filter(has_text="Concurrency proof").get_by_role(
            "button", name="Edit",
        ).click()
        b.locator("#library-content").fill("Unauthorized stale replacement")
        b.locator("#library-save").click()
        b.locator("dialog[open]").get_by_role("button", name="Save changes").click()
        expect(b.locator("#flash")).to_contain_text("reload")
        stored = b.request.get(
            consumer_url + "/api/evidence-library/" + created.json()["library_id"]
        ).json()
        assert stored["content"] == "Initial approved text"
        assert stored["review_status"] == "reviewed"
    finally:
        context_a.close()
        context_b.close()
