"""Web MCP server — REAL internet access for agents (read-only).

Two tools: web_search (DuckDuckGo, no API key needed) and fetch_page
(download + extract readable text). Nothing here posts, submits, or logs
in anywhere — the agent can READ the internet, not act on it.

Run:  python mcp/web/server.py   (stdio transport, for MCP clients)
Test: pytest evals/test_tools.py      (imports the plain functions below)
"""

import html as _html
import os
import re
import sys
import urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, "agents"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from events import emit
except ImportError:  # pragma: no cover

    def emit(*a, **k):  # type: ignore
        return {}

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - plain functions are the contract
    FastMCP = None  # type: ignore

import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ansai-substrate/1.0"
TIMEOUT = 20.0


def _agent() -> str:
    return os.environ.get("AGENT_NAME", "worker")


# ------------------------------------------------------------------ parsing
# Pure functions (no network) so the contract is unit-testable.

_RESULT_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S
)
_SNIPPET_RE = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(s: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", _html.unescape(s))).strip()


def _unwrap_ddg(href: str) -> str:
    """DuckDuckGo wraps external links: //duckduckgo.com/l/?uddg=<encoded>."""
    href = _html.unescape(href.strip())
    if "uddg=" in href:
        q = urllib.parse.urlparse(href if "://" in href else "https:" + href).query
        vals = urllib.parse.parse_qs(q).get("uddg")
        if vals:
            return vals[0]
    if href.startswith("//"):
        return "https:" + href
    return href


def parse_ddg_results(page_html: str, limit: int = 5) -> list[dict]:
    """Extract [{title, url, snippet}] from a DDG html results page."""
    results = []
    snippets = [_clean(s) for s in _SNIPPET_RE.findall(page_html)]
    for i, m in enumerate(_RESULT_RE.finditer(page_html)):
        if len(results) >= limit:
            break
        url = _unwrap_ddg(m.group(1))
        if not url.startswith("http"):
            continue
        results.append(
            {
                "title": _clean(m.group(2)),
                "url": url,
                "snippet": snippets[i] if i < len(snippets) else "",
            }
        )
    return results


def html_to_text(page_html: str, max_chars: int = 8000) -> dict:
    """Extract title + readable text from raw HTML."""
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", page_html, re.S | re.I)
    if m:
        title = _clean(m.group(1))
    body = re.sub(r"<(script|style|nav|footer)[^>]*>.*?</\1>", " ", page_html, flags=re.S | re.I)
    text = _clean(body)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…[truncated]"
    return {"title": title, "text": text}


# --------------------------------------------------------------------- tools


def web_search(query: str, count: int = 5) -> dict:
    """Search the web. Returns [{title, url, snippet}]. Read-only."""
    emit("tool_call", _agent(), f"web_search {query[:60]}")
    count = max(1, min(count, 10))
    try:
        r = httpx.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": UA},
            timeout=TIMEOUT,
            follow_redirects=True,
        )
    except Exception as exc:
        return {"status": "error", "error": f"network: {type(exc).__name__}: {exc}"}
    if r.status_code >= 400:
        return {"status": "error", "error": f"search returned {r.status_code}"}
    results = parse_ddg_results(r.text, count)
    if not results:
        return {"status": "error", "error": "no results parsed (search page layout may have changed)"}
    return {"status": "ok", "query": query, "results": results}


def fetch_page(url: str, max_chars: int = 8000) -> dict:
    """Fetch a page and extract readable text. Read-only; HTML only."""
    emit("tool_call", _agent(), f"fetch_page {url[:80]}")
    if not url.startswith(("http://", "https://")):
        return {"status": "error", "error": "url must start with http(s)://"}
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, follow_redirects=True)
    except Exception as exc:
        return {"status": "error", "error": f"network: {type(exc).__name__}: {exc}"}
    if r.status_code >= 400:
        return {"status": "error", "error": f"page returned {r.status_code}"}
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype and "text" not in ctype:
        return {"status": "error", "error": f"not a readable page ({ctype[:60]})"}
    out = html_to_text(r.text, max_chars=max(500, min(max_chars, 20000)))
    return {"status": "ok", "url": str(r.url), **out}


_TOOLS = [web_search, fetch_page]

if FastMCP is not None:
    mcp = FastMCP("web")
    for _fn in _TOOLS:
        mcp.tool()(_fn)


if __name__ == "__main__":
    if FastMCP is None:
        raise SystemExit("mcp package not installed; plain functions still importable for tests")
    mcp.run()
