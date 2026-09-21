import ipaddress

from instabotai.research import AdaptiveResearchService, Crawl4AIFetcher, FetchedPage, ResearchAccessPolicy
from instabotai.settings import Settings


class StaticResolver:
    def __init__(self, mapping: dict[str, tuple[str, ...]]) -> None:
        self.mapping = mapping

    async def resolve(
        self,
        host: str,
        port: int,
    ) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
        del port
        values = self.mapping.get(host, ())
        return tuple(ipaddress.ip_address(value) for value in values)


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


class FakeRequest:
    def __init__(self, url: str) -> None:
        self.url = url


class FakeRoute:
    def __init__(self, url: str) -> None:
        self.request = FakeRequest(url)
        self.aborted_with: str | None = None
        self.continued = False

    async def abort(self, error_code: str) -> None:
        self.aborted_with = error_code

    async def continue_(self) -> None:
        self.continued = True


def test_access_policy_blocks_meta_owned_and_private_literal_targets() -> None:
    settings = Settings(_env_file=None)
    policy = ResearchAccessPolicy(settings)

    assert not policy.allows("https://instagram.com/example")
    assert not policy.allows("https://sub.facebook.com/page")
    assert not policy.allows("http://127.0.0.1/admin")
    assert not policy.allows("http://169.254.169.254/latest/meta-data")
    assert not policy.allows("http://10.0.0.8/internal")
    assert not policy.allows("http://[::1]/internal")
    assert not policy.allows("http://[::ffff:169.254.169.254]/metadata")
    assert not policy.allows("http://[2002:a9fe:a9fe::]/metadata")
    assert not policy.allows("http://[64:ff9b::a9fe:a9fe]/metadata")
    assert not policy.allows("https://user:password@example.com/private")
    assert policy.allows("https://example.com/research")


async def test_access_policy_rejects_hostname_resolving_to_non_public_address() -> None:
    settings = Settings(_env_file=None)
    policy = ResearchAccessPolicy(
        settings,
        resolver=StaticResolver(
            {
                "public.example": ("93.184.216.34",),
                "rebound.example": ("93.184.216.34", "169.254.169.254"),
            }
        ),
    )

    assert await policy.allows_destination("https://public.example/report")
    assert not await policy.allows_destination("https://rebound.example/report")
    assert not await policy.allows_destination("https://missing.example/report")


async def test_browser_route_guard_blocks_redirect_destination_before_request() -> None:
    settings = Settings(_env_file=None)
    policy = ResearchAccessPolicy(
        settings,
        resolver=StaticResolver(
            {
                "safe.example": ("93.184.216.34",),
                "metadata.example": ("169.254.169.254",),
            }
        ),
    )
    fetcher = Crawl4AIFetcher(settings, access_policy=policy)

    safe_route = FakeRoute("https://safe.example/page")
    await fetcher._route_request(safe_route)
    assert safe_route.continued
    assert safe_route.aborted_with is None

    redirected_route = FakeRoute("http://metadata.example/latest/meta-data")
    await fetcher._route_request(redirected_route)
    assert not redirected_route.continued
    assert redirected_route.aborted_with == "blockedbyclient"


async def test_adaptive_research_prioritizes_relevant_allowed_links() -> None:
    settings = Settings(
        _env_file=None,
        research_confidence_threshold=0.99,
        research_max_pages=2,
        research_min_gain_threshold=0.01,
    )
    fetcher = FakeFetcher()
    policy = ResearchAccessPolicy(
        settings,
        resolver=StaticResolver({"research.example.com": ("93.184.216.34",)}),
    )
    service = AdaptiveResearchService(settings, fetcher, policy)

    report = await service.research(
        "content strategy audience research",
        ["https://research.example.com/seed"],
    )

    assert len(report.pages) == 2
    assert all("instagram.com" not in url for url in fetcher.requested)
    assert fetcher.requested[-1].endswith("/content-strategy")
    assert report.confidence > 0
