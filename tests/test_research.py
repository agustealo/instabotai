from instabotai.research import AdaptiveResearchService, FetchedPage, ResearchAccessPolicy
from instabotai.settings import Settings


class FakeFetcher:
    def __init__(self) -> None:
        self.requested: list[str] = []

    async def fetch(self, url: str) -> FetchedPage:
        self.requested.append(url)
        if url.endswith("/seed"):
            return FetchedPage(
                url=url,
                title="Instagram marketing intelligence",
                markdown="Audience research content strategy market trend analytics.",
                links=(
                    "https://research.example.com/content-strategy",
                    "https://instagram.com/blocked",
                ),
            )
        return FetchedPage(
            url=url,
            title="Content strategy research",
            markdown="Content strategy audience analytics research and trends.",
        )


def test_access_policy_blocks_meta_owned_domains() -> None:
    settings = Settings(_env_file=None)
    policy = ResearchAccessPolicy(settings)

    assert not policy.allows("https://instagram.com/example")
    assert not policy.allows("https://sub.facebook.com/page")
    assert policy.allows("https://example.com/research")


async def test_adaptive_research_prioritizes_relevant_allowed_links() -> None:
    settings = Settings(
        _env_file=None,
        research_confidence_threshold=0.99,
        research_max_pages=2,
        research_min_gain_threshold=0.01,
    )
    fetcher = FakeFetcher()
    service = AdaptiveResearchService(settings, fetcher)

    report = await service.research(
        "content strategy audience research",
        ["https://research.example.com/seed"],
    )

    assert len(report.pages) == 2
    assert all("instagram.com" not in url for url in fetcher.requested)
    assert fetcher.requested[-1].endswith("/content-strategy")
    assert report.confidence > 0
