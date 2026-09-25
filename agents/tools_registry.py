"""Tool registry: which tools each agent profile gets.

Profiles:
  scout  - read-only. GitHub reads, web reads, local reads. Nothing here can
           change anything, send anything, or run anything.
  worker - scout + the gated writes. Every write/shell/send blocks on the
           human approval queue (policy/approvals.py) — the agent cannot act
           silently, it can only ASK.

Chat (office/server.py) runs on the "worker" profile: chat agents read with the
scout tools, and gated writes/shell/sends block on the human approval queue
(policy/approvals.py) — approval cards surface in the chat UI. So chat
executes, but never acts silently.

MCP servers are loaded by file path (not `import mcp...`) because the repo's
own `mcp/` directory would shadow the installed `mcp` package on sys.path.
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_ROOT, "policy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load(name: str, *parts: str):
    path = os.path.join(_ROOT, *parts)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_github = _load("tools_github", "mcp", "github", "server.py")
_web = _load("tools_web", "mcp", "web", "server.py")
_local = _load("tools_local", "mcp", "local", "server.py")


def scout_tools() -> list:
    """Read-only tools: inspect GitHub, read the web, read the local machine."""
    return [
        _github.list_repos,
        _github.read_file,
        _github.list_issues,
        _github.list_pull_requests,
        _github.search_code,
        _web.web_search,
        _web.fetch_page,
        _local.list_dir,
        _local.read_file,
    ]


def worker_tools() -> list:
    """Scout + human-gated writes. Every write/shell/send asks first."""
    return scout_tools() + [
        _github.create_issue,
        _github.comment_on_issue,
        _local.write_file,
        _local.delete_file,
        _local.run_command,
        _local.open_with_default_app,
    ]


def get_tools(profile: str) -> list:
    if profile == "scout":
        return scout_tools()
    if profile == "worker":
        return worker_tools()
    raise ValueError(f"unknown tool profile: {profile!r} (scout|worker)")
