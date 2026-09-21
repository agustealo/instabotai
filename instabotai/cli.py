"""InstabotAI command-line interface."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console

from instabotai.providers.instagram import InstagramGraphClient
from instabotai.research import AdaptiveResearchService, Crawl4AIFetcher, ResearchAccessPolicy
from instabotai.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command("doctor")
def doctor() -> None:
    """Validate runtime configuration without performing account writes."""

    settings = get_settings()
    checks = {
        "environment": settings.environment,
        "graph_api_version": settings.meta_graph_api_version,
        "graph_base_url": settings.meta_graph_base_url,
        "instagram_account_configured": bool(settings.instagram_account_id),
        "instagram_token_configured": settings.instagram_access_token is not None,
        "write_approval_required": settings.require_write_approval,
        "research_max_pages": settings.research_max_pages,
    }
    console.print_json(json.dumps(checks))


@app.command("profile")
def profile() -> None:
    """Read the connected Instagram professional account profile."""

    async def run() -> None:
        async with InstagramGraphClient(get_settings()) as client:
            console.print_json(json.dumps(await client.get_profile()))

    asyncio.run(run())


@app.command("research")
def research(
    objective: str = typer.Argument(..., help="Research objective."),
    seed: list[str] = typer.Option(..., "--seed", help="Public-web seed URL."),
) -> None:
    """Run adaptive public-web research. Meta-owned domains are blocked by default."""

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


if __name__ == "__main__":
    app()
