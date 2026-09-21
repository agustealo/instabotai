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
from instabotai.intelligence import EvidenceItem
from instabotai.settings import get_settings
from instabotai.web import create_app, validate_ui_bind

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"could not read JSON from {path}: {exc}") from exc


def _load_evidence(path: Path) -> list[EvidenceItem]:
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

    console.print_json(_service().runtime_snapshot().model_dump_json())


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
