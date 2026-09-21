"""Adaptive, policy-aware public web research built around Crawl4AI."""

from __future__ import annotations

import heapq
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

from instabotai.domain import ResearchPage, ResearchReport
from instabotai.settings import Settings

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]{1,}", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    markdown: str
    title: str | None = None
    links: tuple[str, ...] = ()


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> FetchedPage:
        """Fetch and normalize one public web page."""


class ResearchAccessPolicy:
    """Allow only explicitly safe public-web targets."""

    def __init__(self, settings: Settings) -> None:
        self._blocked = settings.research_blocked_domains
        self._allowed = settings.research_allowed_domains

    def allows(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = (parsed.hostname or "").lower().rstrip(".")
        if not host:
            return False
        if self._matches(host, self._blocked):
            return False
        return not self._allowed or self._matches(host, self._allowed)

    @staticmethod
    def _matches(host: str, domains: tuple[str, ...]) -> bool:
        return any(host == domain or host.endswith(f".{domain}") for domain in domains)


class Crawl4AIFetcher:
    """Production page fetcher using the current Crawl4AI async API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch(self, url: str) -> FetchedPage:
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

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)

        if not bool(getattr(result, "success", False)):
            message = str(getattr(result, "error_message", "crawl failed"))
            raise RuntimeError(message)

        markdown = self._markdown_text(getattr(result, "markdown", ""))
        title = self._extract_title(result)
        links = self._extract_links(url, getattr(result, "links", None))
        return FetchedPage(url=url, title=title, markdown=markdown, links=links)

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
        if isinstance(raw_links, dict):
            groups = raw_links.values()
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

            if not self._access.allows(url):
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
