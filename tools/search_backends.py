"""Search backends for the AI Search tool.

Backends are *real* network integrations. If none is reachable the tool reports
UNAVAILABLE rather than returning fabricated results.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import requests

from backend.app.core.errors import NetworkError
from backend.app.core.observability import get_logger
from configs.settings import settings

logger = get_logger("search")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    rank: int = 0
    published: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "rank": self.rank,
            "published": self.published,
            **({"extra": self.extra} if self.extra else {}),
        }


class SearchBackend:
    name = "base"

    def available(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:  # pragma: no cover
        raise NotImplementedError


class DuckDuckGoBackend(SearchBackend):
    """DuckDuckGo HTML endpoint (no API key required)."""

    name = "duckduckgo"
    endpoint = "https://html.duckduckgo.com/html/"

    def available(self) -> bool:
        return bool(settings.enable_network_tools)

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        if not self.available():
            raise NetworkError("Network tools are disabled")
        try:
            resp = requests.post(
                self.endpoint,
                data={"q": query, "kl": "wt-wt"},
                headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                timeout=settings.http_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise NetworkError("DuckDuckGo unreachable", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise NetworkError("DuckDuckGo error", detail=f"HTTP {resp.status_code}")

        results: list[SearchResult] = []
        for match in re.finditer(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.S):
            href = html.unescape(match.group(1))
            title = _strip_tags(match.group(2))
            url = _unwrap_ddg(href)
            if not url.startswith("http"):
                continue
            results.append(SearchResult(title=title or url, url=url, source=_domain(url), rank=len(results) + 1))
            if len(results) >= limit:
                break

        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.S)
        for i, snippet in enumerate(snippets[: len(results)]):
            results[i].snippet = _strip_tags(snippet)

        if not results:
            # Lite fallback.
            results = self._lite(query, limit)
        return results

    def _lite(self, query: str, limit: int) -> list[SearchResult]:
        try:
            resp = requests.get(
                "https://lite.duckduckgo.com/lite/",
                params={"q": query},
                headers={"User-Agent": UA},
                timeout=settings.http_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise NetworkError("DuckDuckGo lite unreachable", detail=str(exc)) from exc
        results: list[SearchResult] = []
        for match in re.finditer(r'<a[^>]+class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.S):
            url = html.unescape(match.group(1))
            title = _strip_tags(match.group(2))
            results.append(SearchResult(title=title or url, url=url, source=_domain(url), rank=len(results) + 1))
            if len(results) >= limit:
                break
        return results


class WikipediaBackend(SearchBackend):
    """Structured fallback via the MediaWiki API (no key required)."""

    name = "wikipedia"

    def available(self) -> bool:
        return bool(settings.enable_network_tools)

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        if not self.available():
            raise NetworkError("Network tools are disabled")
        params = {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": limit}
        try:
            resp = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params=params,
                headers={"User-Agent": UA},
                timeout=settings.http_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise NetworkError("Wikipedia unreachable", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise NetworkError("Wikipedia error", detail=f"HTTP {resp.status_code}")
        data = resp.json()
        out: list[SearchResult] = []
        for i, item in enumerate(data.get("query", {}).get("search", []), start=1):
            title = item.get("title", "")
            out.append(
                SearchResult(
                    title=title,
                    url="https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                    snippet=_strip_tags(item.get("snippet", "")),
                    source="en.wikipedia.org",
                    rank=i,
                    published=item.get("timestamp", ""),
                )
            )
        return out


class SemanticScholarBackend(SearchBackend):
    name = "semantic_scholar"

    def available(self) -> bool:
        return bool(settings.enable_network_tools)

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        try:
            resp = requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": query, "limit": limit, "fields": "title,abstract,url,year,authors"},
                headers={"User-Agent": UA},
                timeout=settings.http_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise NetworkError("Semantic Scholar unreachable", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise NetworkError("Semantic Scholar error", detail=f"HTTP {resp.status_code}")
        out: list[SearchResult] = []
        for i, item in enumerate(resp.json().get("data", []), start=1):
            out.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=(item.get("abstract") or "")[:400],
                    source="semanticscholar.org",
                    rank=i,
                    published=str(item.get("year", "")),
                )
            )
        return out


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    return html.unescape(text).strip()


def _unwrap_ddg(href: str) -> str:
    if href.startswith("//duckduckgo.com/l/"):
        parsed = urllib.parse.urlparse("https:" + href)
        params = urllib.parse.parse_qs(parsed.query)
        if "uddg" in params:
            return params["uddg"][0]
    return href


def _domain(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


DEFAULT_BACKENDS: list[SearchBackend] = [DuckDuckGoBackend(), WikipediaBackend(), SemanticScholarBackend()]


def search_web(query: str, limit: int = 8) -> tuple[list[SearchResult], list[str]]:
    """Query backends in order, merging results. Returns (results, backend_errors)."""
    errors: list[str] = []
    merged: list[SearchResult] = []
    seen: set[str] = set()
    for backend in DEFAULT_BACKENDS:
        if not backend.available():
            errors.append(f"{backend.name}: unavailable")
            continue
        try:
            found = backend.search(query, limit=limit)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{backend.name}: {type(exc).__name__}")
            logger.debug("search backend %s failed: %s", backend.name, exc)
            continue
        for item in found:
            key = item.url.rstrip("/")
            if key and key not in seen:
                seen.add(key)
                merged.append(item)
        if len(merged) >= limit:
            break
    for i, item in enumerate(merged, start=1):
        item.rank = i
    return merged[:limit], errors


def fetch_page_text(url: str, max_chars: int = 12000) -> str:
    """Extract readable text from a URL using trafilatura, with an HTML fallback."""
    if not settings.enable_network_tools:
        raise NetworkError("Network tools are disabled")
    try:
        import trafilatura

        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            extracted = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
            if extracted:
                return extracted[:max_chars]
    except Exception as exc:  # noqa: BLE001
        logger.debug("trafilatura failed for %s: %s", url, exc)

    resp = requests.get(url, headers={"User-Agent": UA}, timeout=settings.http_timeout_seconds)
    if resp.status_code >= 400:
        raise NetworkError("Page fetch failed", detail=f"HTTP {resp.status_code}")
    text = re.sub(r"<script.*?</script>", " ", resp.text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    return _strip_tags(text)[:max_chars]


__all__ = ["SearchResult", "search_web", "fetch_page_text", "DuckDuckGoBackend", "WikipediaBackend", "SemanticScholarBackend"]
