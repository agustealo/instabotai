"""Browser-driven consumer journeys, using local state and no Instagram provider writes.

Only public research is mocked. Evidence, review, campaign persistence and UI scripts
run against the actual loopback FastAPI server and canonical SQLite implementation.
These tests are automation evidence, not a substitute for a human acceptance trial.
"""

from __future__ import annotations

import json
import re
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
    expect(page.locator(".library-entry").filter(has_text=title)).to_be_visible()


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


@pytest.mark.parametrize("width", [320, 375, 768, 1024])
def test_viewports_have_accessible_navigation_without_page_overflow(
    browser: Browser, consumer_url: str, width: int,
) -> None:
    """Small devices must expose every destination and never require page-wide panning."""

    context = browser.new_context(
        viewport={"width": width, "height": 800}, reduced_motion="reduce",
    )
    try:
        page = context.new_page()
        uncaught: list[str] = []
        page.on("pageerror", lambda error: uncaught.append(str(error)))
        page.goto(consumer_url, wait_until="domcontentloaded")
        expect(page.locator('.nav-item[data-view="library"]')).to_be_attached()
        mobile = width <= 840
        menu = page.locator("#mobile-nav-toggle")
        if mobile:
            expect(menu).to_be_visible()
            expect(menu).to_have_attribute("aria-expanded", "false")
            expect(page.locator("#primary-nav")).to_be_hidden()
        else:
            expect(menu).to_be_hidden()
            expect(page.locator("#primary-nav")).to_be_visible()

        for destination in ("library", "campaigns", "research", "ai", "setup"):
            if mobile:
                menu.click()
                expect(menu).to_have_attribute("aria-expanded", "true")
            item = page.locator(f'.nav-item[data-view="{destination}"]')
            item.click()
            expect(page.locator("#view-" + destination)).to_have_class(
                re.compile(r"\bis-active\b"),
            )
            expect(item).to_have_attribute("aria-current", "page")
            expect(page.locator("#view-title")).to_be_focused()
            if mobile:
                expect(menu).to_have_attribute("aria-expanded", "false")
                expect(page.locator("#primary-nav")).to_be_hidden()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 2"
            ), f"Horizontal page overflow at {width}px in {destination}"

        assert not uncaught, f"Uncaught JavaScript errors at {width}px: {uncaught}"
    finally:
        context.close()


def test_mobile_keyboard_navigation_skip_link_escape_and_dialog_focus(
    browser: Browser, consumer_url: str,
) -> None:
    """Keyboard users can bypass navigation, close it with Escape, and cancel a review."""

    context = browser.new_context(
        viewport={"width": 375, "height": 760}, reduced_motion="reduce",
    )
    try:
        page = context.new_page()
        page.goto(consumer_url, wait_until="domcontentloaded")
        expect(page.locator('.nav-item[data-view="library"]')).to_be_attached()
        page.keyboard.press("Tab")
        expect(page.get_by_role("link", name="Skip to main content")).to_be_focused()
        page.keyboard.press("Enter")
        assert page.evaluate("location.hash") == "#main-content"

        menu = page.locator("#mobile-nav-toggle")
        menu.focus()
        page.keyboard.press("Enter")
        expect(menu).to_have_attribute("aria-expanded", "true")
        page.keyboard.press("Escape")
        expect(menu).to_have_attribute("aria-expanded", "false")
        expect(menu).to_be_focused()

        menu.click()
        page.locator('.nav-item[data-view="library"]').click()
        save_source(page, "Keyboard focus review source")
        entry = page.locator(".library-entry").filter(has_text="Keyboard focus review source")
        review = entry.get_by_role("button", name="Mark reviewed", exact=True)
        review.focus()
        page.keyboard.press("Enter")
        dialog = page.locator("dialog[open]")
        expect(dialog).to_be_visible()
        assert page.evaluate(
            "Boolean(document.activeElement.closest('dialog[open]'))"
        ), "Dialog must receive keyboard focus"
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        expect(entry).to_contain_text("Unverified")
        expect(page.locator("#library-form")).to_be_visible()
    finally:
        context.close()


def test_library_failure_is_announced_and_manual_refresh_recovers(page: Page) -> None:
    """A server error must not leave the consumer believing the source list is healthy."""

    failure = {"code": "unavailable", "message": "Temporary local storage outage"}
    page.route(
        "**/api/evidence-library?*",
        lambda route: route.fulfill(
            status=503, content_type="application/json", body=json.dumps(failure),
        ),
    )
    open_library(page)
    expect(page.locator("#flash")).to_have_attribute("role", "alert")
    expect(page.locator("#library-status")).to_contain_text(
        "Temporary local storage outage"
    )
    page.unroute("**/api/evidence-library?*")
    page.locator("#library-refresh").click()
    expect(page.locator("#library-status")).to_contain_text("Showing the current page")
    expect(page.locator("#library-list")).to_be_visible()


def test_approval_decision_consequences_and_result_reporting_without_provider_writes(
    page: Page,
) -> None:
    """Exercise the real dialog and action inbox, while replacing provider-affecting routes."""

    proposal = {
        "job_id": "11" * 16,
        "campaign_id": "22" * 16,
        "decision_id": "33" * 16,
        "status": "pending_approval",
        "scheduled_for": "2026-10-19T16:00:00+00:00",
        "attempt_count": 0,
        "max_attempts": 3,
        "last_error": None,
        "provider_result": None,
        "outcome_reward": None,
        "outcome_note": "",
        "created_at": "2026-10-19T14:00:00+00:00",
        "updated_at": "2026-10-19T14:00:00+00:00",
        "action": {
            "action_type": "publish_image",
            "reason": "Approved product brief suggests announcing launch.",
            "confidence": 0.82,
            "target_id": None,
            "idempotency_key": "review-test-action-001",
            "approval": "pending",
            "payload": {
                "image_url": "https://cdn.example.org/product.jpg",
                "caption": "Our verified seasonal product launch.",
            },
        },
    }
    job = dict(proposal)
    posted: list[str] = []

    def handle_jobs(route: object) -> None:
        route.fulfill(
            content_type="application/json",
            body=json.dumps([job]),
        )

    def handle_approve(route: object) -> None:
        posted.append("approve")
        job["status"] = "scheduled"
        job["action"] = {**job["action"], "approval": "approved"}
        route.fulfill(content_type="application/json", body=json.dumps(job))

    page.route("**/api/campaign-jobs?limit=200", handle_jobs)
    page.route("**/api/campaign-jobs/" + job["job_id"] + "/approve", handle_approve)
    page.locator('.nav-item[data-view="campaigns"]').click()
    card = page.locator(".campaign-job-card")
    expect(card).to_have_count(1)
    expect(card).to_contain_text("Approval authorizes a future Instagram write")
    expect(card).to_have_attribute("aria-labelledby", "job-heading-" + job["job_id"])
    approve = card.get_by_role("button", name="Approve Publish an image", exact=False)
    approve.click()
    dialog = page.locator("dialog[open]")
    expect(dialog).to_contain_text("Authorizes this specific action")
    expect(dialog).to_contain_text("Our verified seasonal product launch.")
    expect(dialog).to_contain_text("not proof of accuracy or permission")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    assert posted == [], "Cancelling the dialog must make no backend authorization call"

    approve.click()
    dialog = page.locator("dialog[open]")
    dialog.get_by_role("button", name="Approve", exact=True).click()
    expect(page.locator("#flash")).to_contain_text(
        "approved and moved to the execution queue"
    )
    assert posted == ["approve"]

    page.locator('[data-job-filter="scheduled"]').click()
    expect(page.locator(".campaign-job-card")).to_have_count(1)
    page.evaluate(
        "state.runtime = {policy: {write_approval_required: true}, "
        "instagram: {provider: 'Mock'}}; renderCampaignJobs();"
    )
    execute = page.get_by_role(
        "button", name="Execute Publish an image", exact=False,
    )
    posted_result: list[str] = []

    def handle_execute(route: object) -> None:
        posted_result.append("execute")
        route.fulfill(
            content_type="application/json",
            body=json.dumps({**job, "status": "failed", "last_error": "Provider unavailable"}),
        )

    page.route("**/api/campaign-jobs/" + job["job_id"] + "/execute", handle_execute)
    execute.click()
    dialog = page.locator("dialog[open]")
    expect(dialog).to_contain_text("Requests an Instagram write now")
    dialog.get_by_role("button", name="Execute", exact=True).click()
    expect(page.locator("#flash")).to_contain_text("Instagram execution failed")
    assert posted_result == ["execute"], "Only the intercepted mock received a write"


def test_business_outcome_requires_explicit_score_and_observation(page: Page) -> None:
    """A provider success cannot silently become a guessed business result."""

    job = {
        "job_id": "44" * 16, "campaign_id": "55" * 16, "decision_id": "66" * 16,
        "status": "succeeded", "scheduled_for": "2026-10-19T16:00:00+00:00",
        "attempt_count": 1, "max_attempts": 3, "outcome_reward": None,
        "outcome_note": "", "last_error": None, "provider_result": "mock-media-123",
        "created_at": "2026-10-19T14:00:00+00:00",
        "updated_at": "2026-10-19T14:10:00+00:00",
        "action": {
            "action_type": "publish_image", "reason": "Launch approved.",
            "confidence": 0.9, "approval": "approved", "target_id": None,
            "idempotency_key": "review-test-action-002",
            "payload": {
                "image_url": "https://cdn.example.org/product.jpg",
                "caption": "Our new collection.",
            },
        },
    }
    written: list[dict[str, object]] = []
    page.route(
        "**/api/campaign-jobs?limit=200",
        lambda route: route.fulfill(
            content_type="application/json", body=json.dumps([job]),
        ),
    )
    page.route(
        "**/api/campaign-jobs/" + job["job_id"] + "/outcome",
        lambda route: (
            written.append(route.request.post_data_json),
            route.fulfill(content_type="application/json", body=json.dumps(job)),
        ),
    )
    page.locator('.nav-item[data-view="campaigns"]').click()
    page.locator('[data-job-filter="history"]').click()
    form = page.locator(".outcome-form")
    expect(form).to_be_visible()
    score = form.locator(".outcome-reward")
    note = form.locator(".outcome-note-input")
    expect(score).to_be_empty()
    expect(score).to_have_attribute("required", "")
    expect(note).to_have_attribute("required", "")
    expect(form).to_contain_text("Do not guess")
    form.get_by_role("button", name="Record outcome").click()
    assert written == [], "No default reward or empty observation may be submitted"
    score.fill("0.2")
    note.fill("Two verified inbound enquiries from the launch post.")
    form.get_by_role("button", name="Record outcome").click()
    expect(page.locator("#flash")).to_contain_text("Business outcome recorded")
    assert written == [{
        "reward": 0.2,
        "note": "Two verified inbound enquiries from the launch post.",
    }]
