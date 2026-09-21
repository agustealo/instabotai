"""InstabotAI command-line interface."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

import typer
from rich.console import Console

from instabotai.providers import build_instagram_provider
from instabotai.research import AdaptiveResearchService, Crawl4AIFetcher, ResearchAccessPolicy
from instabotai.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


async def _close_provider(provider: Any) -> None:
    closer = getattr(provider, "aclose", None)
    if closer is not None:
        await closer()


@app.command("doctor")
def doctor() -> None:
    settings = get_settings()
    checks = {
        "environment": settings.environment,
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
        service = AdaptiveResearchService(settings, Crawl4AIFetcher(settings), ResearchAccessPolicy(settings))
        report = await service.research(objective, seed)
        console.print_json(report.model_dump_json())

    asyncio.run(run())


if __name__ == "__main__":
    app()
