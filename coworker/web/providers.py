"""Web search providers — a keyless default + pluggable third-party services.

`duckduckgo` works with no API key (our "starting version of our own"). `tavily` and `brave`
give better results but need a key (configured via the SecretStore / env). All providers
return a uniform `list[SearchResult]`; the heavy client libs are lazy-imported.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

_TIMEOUT = 20.0


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class WebSearchProvider(ABC):
    name: str = "base"
    requires_key: bool = False

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]: ...


class DuckDuckGoProvider(WebSearchProvider):
    """Keyless default via ddgs, duckduckgo_search, or fallback scrapers."""

    name = "duckduckgo"
    requires_key = False

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        # Tier 1: Try DDGS python package (ddgs or duckduckgo_search)
        ddgs_cls = None
        try:
            from ddgs import DDGS
            ddgs_cls = DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS
                ddgs_cls = DDGS
            except ImportError:
                pass

        if ddgs_cls is not None:
            try:
                rows = list(ddgs_cls().text(query, max_results=max_results))
                if rows:
                    return [
                        SearchResult(
                            title=r.get("title", ""),
                            url=r.get("href", "") or r.get("url", ""),
                            snippet=r.get("body", "") or r.get("snippet", ""),
                        )
                        for r in rows
                        if r.get("title") and (r.get("href") or r.get("url"))
                    ]
            except Exception as e:
                logger.warning(f"DDGS search failed in DuckDuckGoProvider: {e}")

        # Tier 2: Try DDG Lite scraper
        try:
            import httpx
            from bs4 import BeautifulSoup
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
                resp = client.post("https://lite.duckduckgo.com/lite/", data={"q": query})
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    lite_results = []
                    for link in soup.find_all("a", class_="result-link"):
                        href = link.get("href", "")
                        title = link.get_text(strip=True)
                        snippet = ""
                        snippet_td = link.find_parent("tr")
                        if snippet_td:
                            next_tr = snippet_td.find_next_sibling("tr")
                            if next_tr:
                                snip_elem = next_tr.find("td", class_="result-snippet")
                                if snip_elem:
                                    snippet = snip_elem.get_text(strip=True)
                        if href and title:
                            if href.startswith("//"):
                                href = "https:" + href
                            lite_results.append(SearchResult(title=title, url=href, snippet=snippet))
                            if len(lite_results) >= max_results:
                                break
                    if lite_results:
                        return lite_results
        except Exception as e:
            logger.warning(f"DDG Lite search failed in DuckDuckGoProvider: {e}")

        # Tier 3: Try Wikipedia search fallback
        try:
            import httpx
            url = "https://en.wikipedia.org/w/api.php"
            params = {
                "action": "opensearch",
                "search": query,
                "limit": max_results,
                "namespace": 0,
                "format": "json"
            }
            with httpx.Client(timeout=8.0) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and len(data) >= 4:
                        titles, snippets, urls = data[1], data[2], data[3]
                        wiki_results = []
                        for title, snippet, u in zip(titles, snippets, urls):
                            if u and title:
                                wiki_results.append(SearchResult(title=title, url=u, snippet=snippet or title))
                        if wiki_results:
                            return wiki_results
        except Exception as e:
            logger.warning(f"Wikipedia fallback failed in DuckDuckGoProvider: {e}")

        return []


class TavilyProvider(WebSearchProvider):
    name = "tavily"
    requires_key = True

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        import httpx

        resp = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": self.api_key, "query": query, "max_results": max_results},
            timeout=_TIMEOUT,
        )
        data = resp.json()
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
            )
            for r in data.get("results", [])
        ]


class BraveProvider(WebSearchProvider):
    name = "brave"
    requires_key = True

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        import httpx

        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "X-Subscription-Token": self.api_key,
                "Accept": "application/json",
            },
            params={"q": query, "count": max_results},
            timeout=_TIMEOUT,
        )
        data = resp.json()
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("description", ""),
            )
            for r in (data.get("web", {}) or {}).get("results", [])
        ]


_PROVIDERS = {
    "duckduckgo": DuckDuckGoProvider,
    "tavily": TavilyProvider,
    "brave": BraveProvider,
}


def build_provider(name: str, api_key: str | None = None) -> WebSearchProvider:
    cls = _PROVIDERS.get(name, DuckDuckGoProvider)
    if cls.requires_key:
        if not api_key:
            raise ValueError(f"web search provider '{name}' needs an API key")
        return cls(api_key)  # type: ignore[call-arg]
    return cls()  # type: ignore[call-arg]


def provider_names() -> list[str]:
    return list(_PROVIDERS)
