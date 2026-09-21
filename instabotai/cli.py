"""InstabotAI command-line interface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from instabotai.intelligence import (
    DecisionJournal,
    EvidenceItem,
    build_intelligence_engine,
    build_reasoning_model,
    probe_reasoning_model,
)
from instabotai.providers import build_instagram_provider
from instabotai.research import AdaptiveResearchService, Crawl4AIFetcher, ResearchAccessPolicy
from instabotai.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


async def _close_provider(provider: Any) -> None:
    closer = getattr(provider, "aclose", None)
    if closer is not None:
        await closer()


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


@app.command("doctor")
def doctor() -> None:
    settings = get_settings()
    checks = {
        "environment": settings.environment,
        "ai_provider": settings.ai_provider,
        "ai_model": settings.ai_model,
        "ai_base_url": settings.ai_base_url,
        "ai_api_key_configured": settings.ai_api_key is not None,
        "ai_critic_enabled": settings.ai_enable_critic,
        "ai_min_decision_score": settings.ai_min_decision_score,
        "instagram_provider": settings.instagram_provider,
        "graph_api_version": settings.meta_graph_api_version,
        "instagram_account_configured": bool(settings.instagram_account_id),
        "instagram_token_configured": settings.instagram_access_token is not None,
        "private_username_configured": bool(settings.private_instagram_username),
        "private_password_configured": settings.private_instagram_password is not None,
        "write_approval_required": settings.require_write_approval,
        "research_max_pages": settings.research_max_pages,
        "state_db_path": settings.state_db_path,
    }
    console.print_json(json.dumps(checks))


@app.command("ai-check")
def ai_check() -> None:
    """Perform a genuine structured inference round trip to the configured AI model."""

    async def run() -> None:
        model = build_reasoning_model(get_settings())
        try:
            probe = await probe_reasoning_model(model)
            console.print_json(probe.model_dump_json())
        finally:
            await _close_provider(model)

    asyncio.run(run())


@app.command("decisions")
def decisions(
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=500, help="Newest decisions to display."),
    ] = 25,
) -> None:
    """Display the newest durable AI decisions and abstentions."""

    journal = DecisionJournal(get_settings().state_db_path)
    try:
        rows = [decision.model_dump(mode="json") for decision in journal.recent(limit)]
        console.print_json(json.dumps(rows, default=str))
    finally:
        journal.close()


@app.command("profile")
def profile() -> None:
    async def run() -> None:
        provider = build_instagram_provider(get_settings())
        try:
            console.print_json(json.dumps(await provider.get_profile(), default=str))
        finally:
            await _close_provider(provider)

    asyncio.run(run())


@app.command("research")
def research(
    objective: Annotated[str, typer.Argument(help="Research objective.")],
    seed: Annotated[list[str], typer.Option("--seed", help="Public-web seed URL.")],
) -> None:
    async def run() -> None:
        settings = get_settings()
        service = AdaptiveResearchService(
            settings,
            Crawl4AIFetcher(settings),
            ResearchAccessPolicy(settings),
        )
        report = await service.research(objective, seed)
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
        engine = build_intelligence_engine(get_settings())
        try:
            decision, action = await engine.plan_instagram_action(
                objective=objective,
                evidence=_load_evidence(evidence_file),
                context=_load_context(context_file),
            )
            result = {
                "decision": decision.model_dump(mode="json"),
                "planned_action": action.model_dump(mode="json") if action is not None else None,
            }
            console.print_json(json.dumps(result, default=str))
        finally:
            await engine.aclose()

    asyncio.run(run())


if __name__ == "__main__":
    app()
