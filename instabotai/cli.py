"""InstabotAI command-line interface."""

from __future__ import annotations

import asyncio
import json
import threading
import webbrowser
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn
from rich.console import Console

from instabotai.application import InstabotApplication
from instabotai.campaigns import CampaignMode
from instabotai.intelligence import EvidenceItem
from instabotai.readiness import ConsumerTrialReadinessService
from instabotai.settings import get_settings
from instabotai.web import create_app, validate_ui_bind

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"could not read JSON from {path}: {exc}") from exc


def _load_evidence(path: Path | None) -> list[EvidenceItem]:
    if path is None:
        return []
    raw = _read_json(path)
    if not isinstance(raw, list):
        raise typer.BadParameter("evidence file must contain a JSON array")
    try:
        return [EvidenceItem.model_validate(item) for item in raw]
    except Exception as exc:
        raise typer.BadParameter(f"invalid evidence file: {exc}") from exc


def _load_context(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raise typer.BadParameter("context file must contain a JSON object")
    return raw


def _service() -> InstabotApplication:
    return InstabotApplication(get_settings())


@app.command("doctor")
def doctor() -> None:
    """Report secret-free runtime configuration without external calls."""

    console.print_json(json.dumps(_service().doctor_payload()))


@app.command("trial-readiness")
def trial_readiness(
    live: Annotated[
        bool,
        typer.Option("--live/--static", help="Run genuine AI and read-only Instagram probes."),
    ] = False,
    require_research: Annotated[
        bool,
        typer.Option(
            "--require-research/--research-optional",
            help="Treat the optional Crawl4AI research capability as a release blocker.",
        ),
    ] = False,
) -> None:
    """Evaluate consumer-trial readiness and return exit code 2 when blockers remain."""

    settings = get_settings()
    report = asyncio.run(
        ConsumerTrialReadinessService(settings).evaluate(
            live=live,
            require_research=require_research,
        )
    )
    console.print_json(report.model_dump_json())
    if not report.ready:
        raise typer.Exit(code=2)


@app.command("ai-check")
def ai_check() -> None:
    """Perform a genuine structured inference round trip to the configured AI model."""

    async def run() -> None:
        console.print_json((await _service().ai_check()).model_dump_json())

    asyncio.run(run())


@app.command("decisions")
def decisions(
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=500, help="Newest decisions to display."),
    ] = 25,
) -> None:
    """Display the newest durable AI decisions and abstentions."""

    rows = [decision.model_dump(mode="json") for decision in _service().recent_decisions(limit)]
    console.print_json(json.dumps(rows, default=str))


@app.command("profile")
def profile() -> None:
    """Read the currently configured Instagram account profile."""

    async def run() -> None:
        console.print_json(json.dumps(await _service().profile(), default=str))

    asyncio.run(run())


@app.command("research")
def research(
    objective: Annotated[str, typer.Argument(help="Research objective.")],
    seed: Annotated[list[str], typer.Option("--seed", help="Public-web seed URL.")],
) -> None:
    """Run bounded adaptive public-web research."""

    async def run() -> None:
        report = await _service().research(objective=objective, seed_urls=seed)
        console.print_json(report.model_dump_json())

    asyncio.run(run())


@app.command("plan")
def plan(
    objective: Annotated[str, typer.Argument(help="Business objective for the AI decision.")],
    evidence_file: Annotated[
        Path,
        typer.Option(
            "--evidence-file",
            exists=True,
            dir_okay=False,
            readable=True,
            help="JSON array of typed evidence records.",
        ),
    ],
    context_file: Annotated[
        Path | None,
        typer.Option(
            "--context-file",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Optional JSON object with additional bounded context.",
        ),
    ] = None,
) -> None:
    """Ask the configured AI system for a reviewed, non-executing Instagram plan."""

    async def run() -> None:
        result = await _service().plan(
            objective=objective,
            evidence=_load_evidence(evidence_file),
            context=_load_context(context_file),
        )
        console.print_json(result.model_dump_json())

    asyncio.run(run())


@app.command("campaign-create")
def campaign_create(
    name: Annotated[str, typer.Argument(help="Campaign name.")],
    objective: Annotated[str, typer.Argument(help="Business objective.")],
    evidence_file: Annotated[
        Path | None,
        typer.Option(
            "--evidence-file",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Optional JSON evidence array.",
        ),
    ] = None,
    context_file: Annotated[
        Path | None,
        typer.Option(
            "--context-file",
            exists=True,
            dir_okay=False,
            readable=True,
            help="Optional JSON context object.",
        ),
    ] = None,
    seed: Annotated[
        list[str] | None,
        typer.Option("--seed", help="Public-web research seed URL."),
    ] = None,
    research: Annotated[
        bool,
        typer.Option("--research/--no-research", help="Research before each planning cycle."),
    ] = False,
    mode: Annotated[
        CampaignMode,
        typer.Option("--mode", help="supervised or policy_managed."),
    ] = CampaignMode.SUPERVISED,
    cadence_minutes: Annotated[
        int,
        typer.Option("--cadence-minutes", min=5, max=43200),
    ] = 1440,
    action_delay_minutes: Annotated[
        int,
        typer.Option("--action-delay-minutes", min=0, max=10080),
    ] = 0,
) -> None:
    """Create a durable campaign in draft state."""

    campaign = _service().create_campaign(
        name=name,
        objective=objective,
        mode=mode,
        cadence_minutes=cadence_minutes,
        action_delay_minutes=action_delay_minutes,
        evidence=_load_evidence(evidence_file),
        context=_load_context(context_file),
        research_seed_urls=seed or [],
        research_before_plan=research,
    )
    console.print_json(campaign.model_dump_json())


@app.command("campaigns")
def campaigns(
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
) -> None:
    """List durable campaigns."""

    rows = [item.model_dump(mode="json") for item in _service().list_campaigns(limit)]
    console.print_json(json.dumps(rows, default=str))


@app.command("campaign-activate")
def campaign_activate(campaign_id: str) -> None:
    """Activate a campaign and make it eligible for planning."""

    console.print_json(_service().activate_campaign(campaign_id).model_dump_json())


@app.command("campaign-pause")
def campaign_pause(campaign_id: str) -> None:
    """Pause future planning and automatic execution for a campaign."""

    console.print_json(_service().pause_campaign(campaign_id).model_dump_json())


@app.command("campaign-plan")
def campaign_plan(campaign_id: str) -> None:
    """Run one immediate campaign planning cycle."""

    async def run() -> None:
        result = await _service().plan_campaign_now(campaign_id)
        console.print_json(result.model_dump_json())

    asyncio.run(run())


@app.command("campaign-jobs")
def campaign_jobs(
    campaign_id: Annotated[str | None, typer.Option("--campaign-id")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
) -> None:
    """List campaign action jobs."""

    rows = [
        job.model_dump(mode="json")
        for job in _service().list_campaign_jobs(campaign_id=campaign_id, limit=limit)
    ]
    console.print_json(json.dumps(rows, default=str))


@app.command("campaign-approve")
def campaign_approve(job_id: str) -> None:
    """Approve one pending campaign action."""

    console.print_json(_service().approve_campaign_job(job_id).model_dump_json())


@app.command("campaign-reject")
def campaign_reject(job_id: str) -> None:
    """Reject one pending campaign action."""

    console.print_json(_service().reject_campaign_job(job_id).model_dump_json())


@app.command("campaign-execute")
def campaign_execute(job_id: str) -> None:
    """Execute one approved/due campaign job through the canonical write service."""

    async def run() -> None:
        console.print_json((await _service().execute_campaign_job(job_id)).model_dump_json())

    asyncio.run(run())


@app.command("campaign-outcome")
def campaign_outcome(
    job_id: str,
    reward: Annotated[float, typer.Option("--reward", min=0.0, max=1.0)],
    note: Annotated[str, typer.Option("--note")] = "",
) -> None:
    """Record the real business outcome that should influence future AI decisions."""

    job = _service().record_campaign_outcome(job_id, reward=reward, note=note)
    console.print_json(job.model_dump_json())


@app.command("worker")
def worker(
    once: Annotated[
        bool,
        typer.Option("--once", help="Run one scheduler tick and exit."),
    ] = False,
    poll_seconds: Annotated[
        float | None,
        typer.Option("--poll-seconds", min=1.0, max=300.0),
    ] = None,
) -> None:
    """Run the durable campaign planner/execution worker."""

    settings = get_settings()
    interval = poll_seconds or settings.campaign_worker_poll_seconds

    async def run() -> None:
        while True:
            tick = await _service().worker_tick()
            console.print_json(tick.model_dump_json())
            if once:
                return
            await asyncio.sleep(interval)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("Worker stopped.")


@app.command("ui")
def ui(
    host: Annotated[
        str | None,
        typer.Option("--host", help="Bind host. Non-loopback requires explicit configuration."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", min=1024, max=65535, help="Bind TCP port."),
    ] = None,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Do not open the consumer console in a browser."),
    ] = False,
) -> None:
    """Launch the local consumer console."""

    settings = get_settings()
    bind_host = validate_ui_bind(settings, host or settings.ui_host)
    bind_port = port or settings.ui_port

    if settings.ui_open_browser and not no_browser:
        browser_host = "127.0.0.1" if bind_host in {"0.0.0.0", "::"} else bind_host
        url = f"http://{browser_host}:{bind_port}"
        timer = threading.Timer(0.8, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()

    uvicorn.run(
        create_app(settings=settings),
        host=bind_host,
        port=bind_port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    app()
