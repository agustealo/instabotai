"""Adaptive, policy-aware public web research built around Crawl4AI."""

from __future__ import annotations

import asyncio
import heapq
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

from instabotai.domain import ResearchPage, ResearchReport
from instabotai.settings import Settings

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]{1,}", re.IGNORECASE)
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
NAT64_WELL_KNOWN = ipaddress.IPv6Network("64:ff9b::/96")
NAT64_LOCAL_USE = ipaddress.IPv6Network("64:ff9b:1::/48")


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    markdown: str
    title: str | None = None
    links: tuple[str, ...] = ()


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> FetchedPage:
        """Fetch and normalize one public web page."""


class HostResolver(Protocol):
    async def resolve(self, host: str, port: int) -> tuple[IPAddress, ...]:
        """Resolve a hostname to every address the operating system returned."""


class SystemHostResolver:
    """Async system DNS resolver used by the research egress policy."""

    async def resolve(self, host: str, port: int) -> tuple[IPAddress, ...]:
        loop = asyncio.get_running_loop()
        records = await loop.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        addresses: list[IPAddress] = []
        for record in records:
            raw = str(record[4][0]).split("%", 1)[0]
            address = ipaddress.ip_address(raw)
            if address not in addresses:
                addresses.append(address)
        return tuple(addresses)


class ResearchAccessPolicy:
    """Allow only explicitly permitted, globally routable public-web targets."""

    def __init__(
        self,
        settings: Settings,
        resolver: HostResolver | None = None,
    ) -> None:
        self._blocked = settings.research_blocked_domains
        self._allowed = settings.research_allowed_domains
        self._resolver = resolver or SystemHostResolver()

    def allows(self, url: str) -> bool:
        """Apply structural/domain policy and reject unsafe literal IP targets."""

        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            return False
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False
        if self._matches(host, self._blocked):
            return False
        if self._allowed and not self._matches(host, self._allowed):
            return False

        literal = self._literal_address(host)
        return literal is None or self._address_is_public(literal)

    async def allows_destination(self, url: str) -> bool:
        """Resolve a target and require every returned address to be globally routable."""

        if not self.allows(url):
            return False
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        literal = self._literal_address(host)
        if literal is not None:
            return self._address_is_public(literal)

        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        try:
            addresses = await self._resolver.resolve(host, port)
        except (OSError, ValueError):
            return False
        return bool(addresses) and all(self._address_is_public(address) for address in addresses)

    @staticmethod
    def _matches(host: str, domains: tuple[str, ...]) -> bool:
        return any(host == domain or host.endswith(f".{domain}") for domain in domains)

    @staticmethod
    def _literal_address(host: str) -> IPAddress | None:
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            return None

    @classmethod
    def _address_is_public(cls, address: IPAddress) -> bool:
        if (
            not address.is_global
            or address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            return False

        if isinstance(address, ipaddress.IPv6Address):
            if address.ipv4_mapped is not None and not cls._address_is_public(address.ipv4_mapped):
                return False
            if address.sixtofour is not None and not cls._address_is_public(address.sixtofour):
                return False
            if address.teredo is not None:
                server, client = address.teredo
                if not cls._address_is_public(server) or not cls._address_is_public(client):
                    return False
            if address in NAT64_WELL_KNOWN or address in NAT64_LOCAL_USE:
                embedded = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
                if not cls._address_is_public(embedded):
                    return False
        return True


class Crawl4AIFetcher:
    """Production page fetcher using Crawl4AI with per-request egress validation."""

    def __init__(
        self,
        settings: Settings,
        access_policy: ResearchAccessPolicy | None = None,
    ) -> None:
        self._settings = settings
        self._access = access_policy or ResearchAccessPolicy(settings)

    async def fetch(self, url: str) -> FetchedPage:
        if not await self._access.allows_destination(url):
            raise RuntimeError("research target rejected by destination policy")

        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
        except ImportError as exc:
            raise RuntimeError(
                "Crawl4AI research support is not installed; install instabotai[research]"
            ) from exc

        browser_config = BrowserConfig(
            headless=True,
            user_agent=self._settings.research_user_agent,
        )
        run_config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=20,
            remove_overlay_elements=True,
            page_timeout=int(self._settings.request_timeout_seconds * 1000),
        )

        crawler = AsyncWebCrawler(config=browser_config)
        crawler.crawler_strategy.set_hook(
            "on_page_context_created",
            self._on_page_context_created,
        )
        async with crawler:
            result = await crawler.arun(url=url, config=run_config)

        if not bool(getattr(result, "success", False)):
            message = str(getattr(result, "error_message", "crawl failed"))
            raise RuntimeError(message)

        actual_url = str(getattr(result, "url", "") or url)
        if not await self._access.allows_destination(actual_url):
            raise RuntimeError("research redirect destination rejected by policy")

        markdown = self._markdown_text(getattr(result, "markdown", ""))
        title = self._extract_title(result)
        links = self._extract_links(actual_url, getattr(result, "links", None))
        return FetchedPage(
            url=actual_url,
            title=title,
            markdown=markdown,
            links=links,
        )

    async def _on_page_context_created(
        self,
        page: Any,
        context: Any,
        **_: Any,
    ) -> Any:
        await context.route("**/*", self._route_request)
        return page

    async def _route_request(self, route: Any) -> None:
        request_url = str(route.request.url)
        scheme = urlparse(request_url).scheme.lower()
        if scheme in {"http", "https"} and not await self._access.allows_destination(request_url):
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    @staticmethod
    def _markdown_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        raw = getattr(value, "raw_markdown", None)
        if isinstance(raw, str):
            return raw
        return str(value or "")

    @staticmethod
    def _extract_title(result: Any) -> str | None:
        metadata = getattr(result, "metadata", None)
        if isinstance(metadata, dict):
            title = metadata.get("title")
            if title:
                return str(title)
        return None

    @staticmethod
    def _extract_links(base_url: str, raw_links: Any) -> tuple[str, ...]:
        links: list[str] = []
        groups: list[Any]
        if isinstance(raw_links, dict):
            groups = list(raw_links.values())
        elif isinstance(raw_links, list):
            groups = [raw_links]
        else:
            groups = []

        for group in groups:
            if not isinstance(group, list):
                continue
            for item in group:
                href: str | None = None
                if isinstance(item, dict):
                    raw_href = item.get("href")
                    href = str(raw_href) if raw_href else None
                elif isinstance(item, str):
                    href = item
                if href:
                    links.append(urljoin(base_url, href))
        return tuple(dict.fromkeys(links))


class AdaptiveResearchService:
    """Research an objective by crawling the most promising public links first."""

    def __init__(
        self,
        settings: Settings,
        fetcher: PageFetcher,
        access_policy: ResearchAccessPolicy | None = None,
    ) -> None:
        self._settings = settings
        self._fetcher = fetcher
        self._access = access_policy or ResearchAccessPolicy(settings)

    async def research(self, objective: str, seed_urls: list[str]) -> ResearchReport:
        objective_tokens = self._tokens(objective)
        if not objective_tokens:
            raise ValueError("objective must contain searchable terms")

        queue: list[tuple[float, int, str]] = []
        seen: set[str] = set()
        blocked: list[str] = []
        failed: list[str] = []
        pages: list[ResearchPage] = []
        counter = 0

        for seed in seed_urls:
            normalized = self._normalize_url(seed)
            if normalized not in seen:
                heapq.heappush(queue, (-1.0, counter, normalized))
                counter += 1

        stopped_early = False
        while queue and len(pages) < self._settings.research_max_pages:
            _, _, url = heapq.heappop(queue)
            if url in seen:
                continue
            seen.add(url)

            if not await self._access.allows_destination(url):
                blocked.append(url)
                continue

            try:
                fetched = await self._fetcher.fetch(url)
            except Exception:
                failed.append(url)
                continue

            relevance = self._relevance(objective_tokens, fetched.markdown, fetched.title)
            pages.append(
                ResearchPage(
                    url=fetched.url,
                    title=fetched.title,
                    markdown=fetched.markdown,
                    outbound_links=fetched.links,
                    relevance=relevance,
                )
            )

            confidence = self._confidence(pages)
            if (
                len(pages) >= self._settings.research_min_pages
                and confidence >= self._settings.research_confidence_threshold
            ):
                stopped_early = True
                break

            candidates: list[tuple[float, str]] = []
            for link in fetched.links:
                normalized = self._normalize_url(link)
                if normalized in seen or not self._access.allows(normalized):
                    continue
                score = self._link_score(objective_tokens, normalized)
                if score >= self._settings.research_min_gain_threshold:
                    candidates.append((score, normalized))

            candidates.sort(reverse=True)
            for score, link in candidates[: self._settings.research_top_k_links]:
                heapq.heappush(queue, (-score, counter, link))
                counter += 1

        return ResearchReport(
            objective=objective,
            pages=tuple(pages),
            blocked_urls=tuple(dict.fromkeys(blocked)),
            failed_urls=tuple(dict.fromkeys(failed)),
            confidence=self._confidence(pages),
            stopped_early=stopped_early,
        )

    @classmethod
    def _relevance(
        cls,
        objective_tokens: frozenset[str],
        markdown: str,
        title: str | None,
    ) -> float:
        if not markdown:
            return 0.0
        body_tokens = cls._tokens(markdown[:12000])
        title_tokens = cls._tokens(title or "")
        body_overlap = len(objective_tokens & body_tokens) / len(objective_tokens)
        title_overlap = len(objective_tokens & title_tokens) / len(objective_tokens)
        return min(1.0, (body_overlap * 0.75) + (title_overlap * 0.25))

    @classmethod
    def _link_score(cls, objective_tokens: frozenset[str], url: str) -> float:
        link_tokens = cls._tokens(url.replace("/", " ").replace("-", " "))
        if not link_tokens:
            return 0.0
        overlap = len(objective_tokens & link_tokens) / len(objective_tokens)
        return min(1.0, overlap)

    @staticmethod
    def _confidence(pages: list[ResearchPage]) -> float:
        if not pages:
            return 0.0
        remaining_uncertainty = 1.0
        for page in sorted(pages, key=lambda item: item.relevance, reverse=True)[:5]:
            remaining_uncertainty *= 1.0 - (page.relevance * 0.65)
        return min(1.0, 1.0 - remaining_uncertainty)

    @staticmethod
    def _tokens(value: str) -> frozenset[str]:
        return frozenset(token.lower() for token in TOKEN_RE.findall(value))

    @staticmethod
    def _normalize_url(value: str) -> str:
        parsed = urlparse(value.strip())
        if not parsed.scheme:
            parsed = urlparse(f"https://{value.strip()}")
        return parsed._replace(fragment="").geturl()
