"""GitHub MCP server — REAL (not a stub).

Wraps the GitHub REST API so agents can inspect the founder's repos, read
code, and (with human approval) file issues and comments. The model never
sees the token: it lives in the process environment (GITHUB_TOKEN, set in
gateway/.env which is gitignored) and only tool RESULTS go back to the model.

Auth: create a fine-grained PAT at https://github.com/settings/tokens —
read access to the repos the agent should see; add issues:read/write only
if you want agents filing issues. Paste it as GITHUB_TOKEN in gateway/.env.

Writes (create_issue, comment_on_issue) are OUTBOUND SENDS and go through
policy/approvals.py — the agent blocks until a human approves or denies.

Run:  python mcp/github/server.py   (stdio transport, for MCP clients)
Test: pytest evals/test_tools.py      (imports the plain functions below)
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, "policy"), os.path.join(_ROOT, "agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from approvals import request_approval
except ImportError:  # pragma: no cover - policy/ not on path in odd embeds

    def request_approval(action, timeout=3600):  # type: ignore
        return False

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

API = "https://api.github.com"
TIMEOUT = 25.0


def _agent() -> str:
    return os.environ.get("AGENT_NAME", "worker")


def _token() -> str:
    return os.environ.get("GITHUB_TOKEN", "").strip()


def _no_token() -> dict:
    return {
        "status": "error",
        "error": "GITHUB_TOKEN is not set — create a PAT at "
        "github.com/settings/tokens and add it to gateway/.env (gitignored).",
    }


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ansai-substrate",
    }


def _get(path: str, params: dict | None = None) -> dict:
    """GET helper. Returns {"status":"ok","data":...} or {"status":"error",...}."""
    if not _token():
        return _no_token()
    try:
        r = httpx.get(API + path, headers=_headers(), params=params or {}, timeout=TIMEOUT)
    except Exception as exc:
        return {"status": "error", "error": f"network: {type(exc).__name__}: {exc}"}
    if r.status_code >= 400:
        return {"status": "error", "error": f"github {r.status_code}: {r.text[:300]}"}
    return {"status": "ok", "data": r.json()}


def _post(path: str, payload: dict) -> dict:
    if not _token():
        return _no_token()
    try:
        r = httpx.post(API + path, headers=_headers(), json=payload, timeout=TIMEOUT)
    except Exception as exc:
        return {"status": "error", "error": f"network: {type(exc).__name__}: {exc}"}
    if r.status_code >= 400:
        return {"status": "error", "error": f"github {r.status_code}: {r.text[:300]}"}
    return {"status": "ok", "data": r.json()}


def _check_repo(repo: str) -> str | None:
    if "/" not in repo or repo.count("/") != 1:
        return "repo must be 'owner/name'"
    return None


# ---------------------------------------------------------------- read tools

def list_repos(limit: int = 30) -> dict:
    """List repos the token can see, most recently updated first."""
    emit("tool_call", _agent(), f"list_repos limit={limit}")
    out = _get("/user/repos", {"per_page": max(1, min(limit, 100)), "sort": "updated"})
    if out["status"] != "ok":
        return out
    return {
        "status": "ok",
        "repos": [
            {
                "full_name": r["full_name"],
                "private": r["private"],
                "description": r.get("description"),
                "default_branch": r.get("default_branch"),
                "updated_at": r.get("updated_at"),
                "html_url": r.get("html_url"),
            }
            for r in out["data"]
        ],
    }


def read_file(repo: str, path: str, ref: str = "") -> dict:
    """Read a file (or list a directory) in a repo. path like 'README.md' or 'src/'."""
    emit("tool_call", _agent(), f"read_file {repo}:{path}")
    err = _check_repo(repo)
    if err:
        return {"status": "error", "error": err}
    params = {"ref": ref} if ref else None
    out = _get(f"/repos/{repo}/contents/{path.strip('/')}", params)
    if out["status"] != "ok":
        return out
    data = out["data"]
    if isinstance(data, list):  # directory listing
        return {
            "status": "ok",
            "type": "dir",
            "entries": [{"name": e["name"], "type": e["type"], "path": e["path"]} for e in data],
        }
    if data.get("encoding") == "base64":
        import base64

        try:
            text = base64.b64decode(data["content"]).decode("utf-8", "replace")
        except Exception:
            return {"status": "error", "error": "file is not decodable text"}
        if len(text) > 20000:
            text = text[:20000] + "\n…[truncated]"
        return {"status": "ok", "type": "file", "path": data.get("path"), "text": text}
    return {"status": "error", "error": "unsupported content encoding"}


def list_issues(repo: str, state: str = "open", limit: int = 20) -> dict:
    """List issues (not PRs) in a repo."""
    emit("tool_call", _agent(), f"list_issues {repo} {state}")
    err = _check_repo(repo)
    if err:
        return {"status": "error", "error": err}
    out = _get(f"/repos/{repo}/issues", {"state": state, "per_page": max(1, min(limit, 50))})
    if out["status"] != "ok":
        return out
    return {
        "status": "ok",
        "issues": [
            {
                "number": i["number"],
                "title": i["title"],
                "state": i["state"],
                "user": (i.get("user") or {}).get("login"),
                "html_url": i.get("html_url"),
            }
            for i in out["data"]
            if "pull_request" not in i
        ],
    }


def list_pull_requests(repo: str, state: str = "open", limit: int = 20) -> dict:
    """List pull requests in a repo."""
    emit("tool_call", _agent(), f"list_pull_requests {repo} {state}")
    err = _check_repo(repo)
    if err:
        return {"status": "error", "error": err}
    out = _get(f"/repos/{repo}/pulls", {"state": state, "per_page": max(1, min(limit, 50))})
    if out["status"] != "ok":
        return out
    return {
        "status": "ok",
        "pull_requests": [
            {
                "number": p["number"],
                "title": p["title"],
                "state": p["state"],
                "user": (p.get("user") or {}).get("login"),
                "html_url": p.get("html_url"),
            }
            for p in out["data"]
        ],
    }


def search_code(query: str, limit: int = 10) -> dict:
    """Search code across repos the token can see. query e.g. 'litellm num_workers'."""
    emit("tool_call", _agent(), f"search_code {query[:60]}")
    out = _get("/search/code", {"q": query, "per_page": max(1, min(limit, 30))})
    if out["status"] != "ok":
        return out
    return {
        "status": "ok",
        "total": out["data"].get("total_count"),
        "results": [
            {
                "repo": (i.get("repository") or {}).get("full_name"),
                "path": i.get("path"),
                "html_url": i.get("html_url"),
            }
            for i in out["data"].get("items", [])
        ],
    }


# --------------------------------------------------------------- write tools
# Outbound sends: ALWAYS through human approval. The agent blocks here until
# the founder approves/denies via: python policy/approve.py approve|deny <id>


def create_issue(repo: str, title: str, body: str = "") -> dict:
    """File a new issue. BLOCKS on human approval — nothing is sent silently."""
    emit("tool_call", _agent(), f"create_issue {repo}: {title[:60]}")
    err = _check_repo(repo)
    if err:
        return {"status": "error", "error": err}
    ok = request_approval(
        {
            "kind": "github-write",
            "summary": f"Create issue in {repo}: {title}",
            "payload": {"repo": repo, "title": title, "body": body[:2000]},
        }
    )
    if not ok:
        return {"status": "denied", "error": "human denied (or timed out) the issue creation"}
    out = _post(f"/repos/{repo}/issues", {"title": title, "body": body})
    if out["status"] != "ok":
        return out
    d = out["data"]
    return {"status": "ok", "number": d["number"], "html_url": d.get("html_url")}


def comment_on_issue(repo: str, number: int, body: str) -> dict:
    """Comment on an issue or PR. BLOCKS on human approval — nothing sent silently."""
    emit("tool_call", _agent(), f"comment_on_issue {repo}#{number}")
    err = _check_repo(repo)
    if err:
        return {"status": "error", "error": err}
    ok = request_approval(
        {
            "kind": "github-write",
            "summary": f"Comment on {repo}#{number}: {body[:120]}",
            "payload": {"repo": repo, "number": number, "body": body[:2000]},
        }
    )
    if not ok:
        return {"status": "denied", "error": "human denied (or timed out) the comment"}
    out = _post(f"/repos/{repo}/issues/{number}/comments", {"body": body})
    if out["status"] != "ok":
        return out
    return {"status": "ok", "html_url": out["data"].get("html_url")}


_TOOLS = [
    list_repos,
    read_file,
    list_issues,
    list_pull_requests,
    search_code,
    create_issue,
    comment_on_issue,
]

if FastMCP is not None:
    mcp = FastMCP("github")
    for _fn in _TOOLS:
        mcp.tool()(_fn)


if __name__ == "__main__":
    if FastMCP is None:
        raise SystemExit("mcp package not installed; plain functions still importable for tests")
    mcp.run()
