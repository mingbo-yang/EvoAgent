"""Web tools — web_fetch and web_search with egress (SSRF) protection.

Both tools validate every URL — including redirect hops — through the egress
policy before issuing a request. They are network side-effecting and are
classified as ``network`` actions so the permission policy can gate them.
"""

import asyncio
import html
import os
import re
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx
from pydantic import BaseModel, Field

from evoagent.core.ids import generate_id
from evoagent.sandbox.egress import check_url_allowed
from evoagent.tools.base import BaseTool, RiskLevel
from evoagent.tools.schema import ToolResult

_DEFAULT_TIMEOUT = 20.0
_HTML_SEARCH_TIMEOUT = 3.0
_MAX_REDIRECTS = 5
_USER_AGENT = (
    "Mozilla/5.0 (compatible; EvoAgent/1.0; +https://github.com/mingbo-yang/EvoAgent)"
)

# Tavily search API (optional fallback). The key is read ONLY from the
# TAVILY_API_KEY environment variable — it must never be hard-coded or logged.
_TAVILY_ENDPOINT = "https://api.tavily.com/search"

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANKS_RE = re.compile(r"\n\s*\n\s*")


def _egress_allowlist() -> list[str] | None:
    """Optional comma-separated host allowlist from EVOAGENT_EGRESS_ALLOWLIST."""
    raw = os.getenv("EVOAGENT_EGRESS_ALLOWLIST", "").strip()
    if not raw:
        return None
    return [h.strip() for h in raw.split(",") if h.strip()]


def _tavily_api_key() -> str | None:
    """Tavily API key from the TAVILY_API_KEY environment variable, if set."""
    key = os.getenv("TAVILY_API_KEY", "").strip()
    return key or None


def html_to_text(content: str) -> str:
    """Crudely convert HTML to readable plain text."""
    content = _SCRIPT_STYLE_RE.sub(" ", content)
    content = _TAG_RE.sub(" ", content)
    content = html.unescape(content)
    content = _WS_RE.sub(" ", content)
    content = _BLANKS_RE.sub("\n\n", content)
    return content.strip()


async def _fetch_with_egress(
    client: httpx.AsyncClient, url: str, allowlist: list[str] | None
) -> httpx.Response:
    """GET ``url`` following redirects manually, re-checking egress per hop."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        # DNS/egress validation can block in socket.getaddrinfo; run it in a
        # worker thread so outer asyncio timeouts remain responsive.
        ok, reason = await asyncio.to_thread(
            check_url_allowed, current, allowlist=allowlist
        )
        if not ok:
            raise PermissionError(reason)
        resp = await client.get(current, follow_redirects=False)
        if resp.is_redirect and "location" in resp.headers:
            current = urljoin(current, resp.headers["location"])
            continue
        return resp
    raise RuntimeError(f"Too many redirects fetching {url}.")


class WebFetchInput(BaseModel):
    url: str = Field(..., description="The http(s) URL to fetch.")
    max_length: int = Field(
        default=20000, ge=1, le=200000,
        description="Maximum characters of body to return.",
    )
    raw: bool = Field(default=False, description="If true, return raw HTML instead of text.")


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = (
        "Fetch a web page over http(s) and return its text content. Use for "
        "reading documentation or pages whose URL you already know. Blocked from "
        "reaching private/loopback addresses."
    )
    input_schema = WebFetchInput
    risk_level = RiskLevel.HIGH

    async def run(self, url: str, max_length: int = 20000, raw: bool = False) -> ToolResult:
        allowlist = _egress_allowlist()
        try:
            async with httpx.AsyncClient(
                timeout=_DEFAULT_TIMEOUT, headers={"User-Agent": _USER_AGENT},
                trust_env=False,
            ) as client:
                resp = await _fetch_with_egress(client, url, allowlist)
        except PermissionError as e:
            return ToolResult(call_id=generate_id("call"), name=self.name, success=False,
                              error=f"Egress blocked: {e}")
        except (httpx.HTTPError, RuntimeError) as e:
            return ToolResult(call_id=generate_id("call"), name=self.name, success=False,
                              error=f"Fetch failed: {e}")

        if resp.status_code >= 400:
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False,
                error=f"HTTP {resp.status_code} fetching {url}.",
                metadata={"status_code": resp.status_code, "url": str(resp.url)},
            )
        body = resp.text
        content_type = resp.headers.get("content-type", "")
        if not raw and "html" in content_type.lower():
            body = html_to_text(body)
        truncated = len(body) > max_length
        body = body[:max_length]
        return ToolResult(
            call_id=generate_id("call"), name=self.name, success=True, output=body,
            metadata={
                "status_code": resp.status_code,
                "url": str(resp.url),
                "content_type": content_type,
                "truncated": truncated,
            },
        )


class WebSearchInput(BaseModel):
    query: str = Field(..., description="The search query.")
    max_results: int = Field(
        default=5, ge=1, le=25, description="Maximum number of results to return."
    )


# Bing HTML results: organic hits are <h2><a href="URL">TITLE</a></h2> with a
# snippet paragraph inside a <div class="b_caption">. We match anchors and
# captions directly (block matching is brittle: Bing nests <li> and adds
# variable attributes/classes).
_BING_TITLE_RE = re.compile(
    r'<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_BING_SNIPPET_RE = re.compile(
    r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)

# DuckDuckGo HTML endpoint (fallback): <a class="result__a" href="URL">TITLE</a>
_DDG_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_DDG_SNIPPET_RE = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def _decode_ddg_href(href: str) -> str:
    """DuckDuckGo wraps targets in /l/?uddg=<encoded>; unwrap when present."""
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0])
    return href


def _parse_bing(body: str, max_results: int) -> list[tuple[str, str, str]]:
    titles = _BING_TITLE_RE.findall(body)
    snippets = _BING_SNIPPET_RE.findall(body)
    out: list[tuple[str, str, str]] = []
    for i, (href, title_html) in enumerate(titles[:max_results]):
        snippet = html_to_text(snippets[i]) if i < len(snippets) else ""
        out.append((html_to_text(title_html), href, snippet))
    return out


def _parse_ddg(body: str, max_results: int) -> list[tuple[str, str, str]]:
    links = _DDG_RESULT_RE.findall(body)
    snippets = _DDG_SNIPPET_RE.findall(body)
    out: list[tuple[str, str, str]] = []
    for i, (href, title_html) in enumerate(links[:max_results]):
        snippet = html_to_text(snippets[i]) if i < len(snippets) else ""
        out.append((html_to_text(title_html), _decode_ddg_href(href), snippet))
    return out


async def _tavily_search(
    client: httpx.AsyncClient, query: str, max_results: int,
    allowlist: list[str] | None,
) -> list[tuple[str, str, str]]:
    """Query the Tavily search API and return (title, url, snippet) triples.

    The API key is read from TAVILY_API_KEY and sent only in the Authorization
    header of this single HTTPS request; it is never persisted or logged.
    """
    key = _tavily_api_key()
    if not key:
        return []
    ok, reason = check_url_allowed(_TAVILY_ENDPOINT, allowlist=allowlist)
    if not ok:
        raise PermissionError(reason)
    resp = await client.post(
        _TAVILY_ENDPOINT,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        },
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Tavily HTTP {resp.status_code}")
    data = resp.json()
    out: list[tuple[str, str, str]] = []
    for r in (data.get("results") or [])[:max_results]:
        out.append((
            str(r.get("title", "")).strip(),
            str(r.get("url", "")).strip(),
            str(r.get("content", "")).strip(),
        ))
    return out


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web and return a list of result titles, URLs, and snippets. "
        "Use to discover relevant pages when you don't know the URL."
    )
    input_schema = WebSearchInput
    risk_level = RiskLevel.HIGH

    # HTML scraping backends, tried in order first (free, no key required).
    _BACKENDS = (
        ("https://www.bing.com/search?q={q}", "_parse_bing"),
        ("https://html.duckduckgo.com/html/?q={q}", "_parse_ddg"),
    )

    @staticmethod
    def _format(query, hits, engine):
        results = [
            f"{i + 1}. {title}\n   {href}\n   {snippet}".rstrip()
            for i, (title, href, snippet) in enumerate(hits)
        ]
        return ToolResult(
            call_id=generate_id("call"), name="web_search", success=True,
            output="\n\n".join(results),
            metadata={"query": query, "results": len(results), "engine": engine},
        )

    async def run(self, query: str, max_results: int = 5) -> ToolResult:
        allowlist = _egress_allowlist()
        parsers = {"_parse_bing": _parse_bing, "_parse_ddg": _parse_ddg}
        last_error = ""
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT, headers={"User-Agent": _USER_AGENT},
            trust_env=False,
        ) as client:
            # 1) Free HTML backends first, but race them concurrently under a
            #    short total budget. This keeps the UI responsive when one
            #    backend stalls and still preserves the "free before API" rule.
            html_tasks = [
                asyncio.create_task(
                    self._try_html_backend(
                        client, tmpl, parser_name, parsers, query, max_results, allowlist
                    )
                )
                for tmpl, parser_name in self._BACKENDS
            ]
            try:
                for completed in asyncio.as_completed(
                    html_tasks, timeout=_HTML_SEARCH_TIMEOUT
                ):
                    hits, engine, err = await completed
                    if hits:
                        for p in html_tasks:
                            p.cancel()
                        return self._format(query, hits, engine)
                    if err:
                        last_error = err
            except TimeoutError:
                last_error = "Timed out waiting for free HTML search backends"
            finally:
                for task in html_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*html_tasks, return_exceptions=True)

            # 2) Fallback to the Tavily API only if the free backends produced
            #    nothing and a TAVILY_API_KEY is configured.
            if _tavily_api_key():
                try:
                    hits = await _tavily_search(client, query, max_results, allowlist)
                    if hits:
                        return self._format(query, hits, "tavily")
                except PermissionError as e:
                    last_error = f"Tavily egress blocked: {e}"
                except (httpx.HTTPError, RuntimeError, ValueError) as e:
                    last_error = f"Tavily failed: {type(e).__name__}: {e}"

        if last_error:
            return ToolResult(call_id=generate_id("call"), name=self.name,
                              success=False, error=f"Search failed: {last_error}")
        return ToolResult(
            call_id=generate_id("call"), name=self.name, success=True,
            output="No results found.", metadata={"query": query, "results": 0},
        )

    async def _try_html_backend(
        self,
        client: httpx.AsyncClient,
        tmpl: str,
        parser_name: str,
        parsers,
        query: str,
        max_results: int,
        allowlist: list[str] | None,
    ) -> tuple[list[tuple[str, str, str]], str, str]:
        url = tmpl.format(q=quote_plus(query))
        engine = urlparse(url).netloc
        try:
            resp = await asyncio.wait_for(
                _fetch_with_egress(client, url, allowlist),
                timeout=_HTML_SEARCH_TIMEOUT,
            )
        except PermissionError as e:
            return [], engine, f"Egress blocked: {e}"
        except TimeoutError:
            return [], engine, f"Timed out fetching {engine}"
        except (httpx.HTTPError, RuntimeError) as e:
            return [], engine, f"{type(e).__name__}: {e}"
        if resp.status_code >= 400:
            return [], engine, f"HTTP {resp.status_code} from {engine}"
        return parsers[parser_name](resp.text, max_results), engine, ""
