"""Local-machine MCP server — REAL access to the founder's computer.

The agents run on the founder's own machine (the office server is local), so
these tools give them hands there: list/read files, write files, delete, and
run shell commands. This is the most powerful toolset in the substrate, so it
is also the most fenced:

  sandbox  - AGENT_LOCAL_ROOT (default: this repo). Reads/writes inside the
             root are free. Anything outside the root needs human approval.
             AGENT_LOCAL_UNRESTRICTED=1 lifts the fence (his explicit opt-in).
  secrets  - read_file REFUSES credential-looking files (.env, *secret*,
             *credential*, *.pem, *.key, ssh private keys). Agents work for
             the founder; they don't get his keys.
  shell    - run_command ALWAYS blocks on human approval, except a small
             read-only allowlist (git status, ls/dir, --version probes...).
             The exact command is shown to the human before it runs.
  delete   - always blocks on human approval. No silent deletes, ever.
  open     - open_with_default_app launches a URL in the browser or a file in
             its default app (VS Code, Excel, ...). Always asks approval: it
             acts visibly on the founder's machine.
  audit    - every call is appended to policy/audit.jsonl (gitignored, never
             committed): timestamp, agent, tool, and a summary (never file
             contents, never secrets).

Out-of-scope reads/writes/deletes/shell go through policy/approvals.py: the
agent blocks until the founder runs `python policy/approve.py approve|deny`.

Run:  python mcp/local/server.py   (stdio transport, for MCP clients)
Test: pytest evals/test_tools.py      (imports the plain functions below)
"""

import datetime
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))  # repo root by default
for _p in (os.path.join(_ROOT, "policy"), os.path.join(_ROOT, "agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from approvals import request_approval
except ImportError:  # pragma: no cover

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

SANDBOX_ROOT = os.path.abspath(os.environ.get("AGENT_LOCAL_ROOT", _ROOT))
UNRESTRICTED = os.environ.get("AGENT_LOCAL_UNRESTRICTED", "") == "1"
AUDIT_PATH = os.environ.get(
    "AGENT_AUDIT_LOG", os.path.join(_ROOT, "policy", "audit.jsonl")
)
IS_WINDOWS = os.name == "nt"

# Credential-looking files the agent may never read (founder's keys stay his).
_SECRET_NAMES = {"id_rsa", "id_ed25519", "id_ecdsa", ".netrc", "_netrc"}
_SECRET_PARTS = ("secret", "credential", "credentials")


def _agent() -> str:
    return os.environ.get("AGENT_NAME", "worker")


def _audit(tool: str, summary: str) -> None:
    try:
        with open(AUDIT_PATH, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(
                            timespec="seconds"
                        ),
                        "agent": _agent(),
                        "tool": tool,
                        "summary": summary[:200],
                    }
                )
                + "\n"
            )
    except Exception:
        pass  # auditing must never break the tool itself


def _is_secret(path: str) -> bool:
    name = os.path.basename(path).lower()
    if name == ".env" or name.startswith(".env."):
        return True
    if name in _SECRET_NAMES or name.startswith("id_"):
        return True
    if name.endswith((".pem", ".key")):
        return True
    return any(part in name for part in _SECRET_PARTS)


def _resolve(path: str) -> tuple[str | None, str | None]:
    """Resolve a user path against the sandbox. Returns (abs_path, error).

    Relative paths are anchored at the sandbox root (the agent's workspace),
    not the process CWD — so "note.txt" means <sandbox>/note.txt.
    """
    expanded = os.path.expanduser(path or ".")
    p = os.path.abspath(
        expanded if os.path.isabs(expanded) else os.path.join(SANDBOX_ROOT, expanded)
    )
    if UNRESTRICTED:
        return p, None
    try:
        inside = os.path.commonpath([p, SANDBOX_ROOT]) == SANDBOX_ROOT
    except ValueError:
        inside = False
    if not inside:
        return None, (
            f"path is outside the agent sandbox ({SANDBOX_ROOT}). "
            "Set AGENT_LOCAL_UNRESTRICTED=1 to lift the fence, or approve this call."
        )
    return p, None


# ------------------------------------------------------------------ read-only

def list_dir(path: str = ".") -> dict:
    """List a directory inside the sandbox. Read-only, no approval needed."""
    emit("tool_call", _agent(), f"list_dir {path[:80]}")
    p, err = _resolve(path)
    if err:
        return {"status": "error", "error": err}
    if not os.path.isdir(p):
        return {"status": "error", "error": "not a directory"}
    try:
        entries = []
        for name in sorted(os.listdir(p)):
            full = os.path.join(p, name)
            entries.append(
                {
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                }
            )
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    _audit("list_dir", path)
    return {"status": "ok", "path": p, "entries": entries[:500]}


def read_file(path: str, max_chars: int = 12000) -> dict:
    """Read a text file inside the sandbox. Credential files are refused."""
    emit("tool_call", _agent(), f"read_file {path[:80]}")
    p, err = _resolve(path)
    if err:
        return {"status": "error", "error": err}
    if _is_secret(p):
        _audit("read_file", f"BLOCKED secret: {path}")
        return {
            "status": "blocked",
            "error": "credential-looking files are off-limits to agents "
            "(secrets stay with the founder)",
        }
    if not os.path.isfile(p):
        return {"status": "error", "error": "not a file"}
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read(max(500, min(max_chars, 50000)))
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    _audit("read_file", f"{path} ({len(text)} chars)")
    return {"status": "ok", "path": p, "text": text}


# ------------------------------------------------------------------ writes

def _needs_approval_for_write(p: str) -> str | None:
    """None if free, else the reason approval is required."""
    if UNRESTRICTED:
        return None
    try:
        inside = os.path.commonpath([p, SANDBOX_ROOT]) == SANDBOX_ROOT
    except ValueError:
        inside = False
    if not inside:
        return f"outside sandbox root ({SANDBOX_ROOT})"
    return None


def write_file(path: str, content: str) -> dict:
    """Write (create or overwrite) a text file. Outside the sandbox: approval."""
    emit("tool_call", _agent(), f"write_file {path[:80]}")
    expanded = os.path.expanduser(path)
    p = os.path.abspath(
        expanded if os.path.isabs(expanded) else os.path.join(SANDBOX_ROOT, expanded)
    )
    reason = _needs_approval_for_write(p)
    if reason:
        ok = request_approval(
            {
                "kind": "local-write",
                "summary": f"Write file outside sandbox: {p} ({len(content)} chars)",
                "payload": {"path": p, "bytes": len(content), "reason": reason},
            }
        )
        if not ok:
            return {"status": "denied", "error": "human denied (or timed out) the write"}
    if _is_secret(p):
        return {"status": "blocked", "error": "agents may not write credential files"}
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    _audit("write_file", f"{p} ({len(content)} chars)")
    return {"status": "ok", "path": p, "bytes": len(content)}


def delete_file(path: str) -> dict:
    """Delete a file or empty dir. ALWAYS blocks on human approval."""
    emit("tool_call", _agent(), f"delete_file {path[:80]}")
    p = os.path.abspath(os.path.expanduser(path))
    ok = request_approval(
        {
            "kind": "delete",
            "summary": f"Delete: {p}",
            "payload": {"path": p},
        }
    )
    if not ok:
        return {"status": "denied", "error": "human denied (or timed out) the delete"}
    try:
        if os.path.isdir(p):
            os.rmdir(p)
        else:
            os.remove(p)
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    _audit("delete_file", f"APPROVED delete: {p}")
    return {"status": "ok", "path": p}


# ------------------------------------------------------------------ shell

# Read-only commands that skip approval. Prefix-matched on the stripped input.
# Deliberately narrow: no cat/type (would bypass the secret blocklist), no
# pipes/redirects smuggling side effects — those go through approval.
ALLOWLIST_PREFIXES = (
    "git status",
    "git log",
    "git diff --stat",
    "git branch",
    "ls",
    "dir",
    "pwd",
    "whoami",
    "echo",
    "python --version",
    "python3 --version",
    "node --version",
    "npm --version",
    "docker ps",
    "docker --version",
)


def is_allowlisted(command: str) -> bool:
    cmd = command.strip().lower()
    if any(tok in cmd for tok in ("|", ">", "<", "&&", ";", "`", "$(")):
        return False
    return cmd.startswith(ALLOWLIST_PREFIXES)


def run_command(command: str, timeout: int = 60, workdir: str = ".") -> dict:
    """Run a shell command on the founder's machine.

    Blocks on human approval unless the command matches the read-only
    allowlist. The human sees the EXACT command before it runs. Output is
    captured and truncated; nothing streams to the model raw.
    """
    emit("tool_call", _agent(), f"run_command {command[:80]}")
    wd, err = _resolve(workdir)
    if err:
        return {"status": "error", "error": err}
    if not is_allowlisted(command):
        ok = request_approval(
            {
                "kind": "shell",
                "summary": f"Run shell command: {command[:300]}",
                "payload": {"command": command, "workdir": wd, "timeout": timeout},
            }
        )
        if not ok:
            return {"status": "denied", "error": "human denied (or timed out) the command"}
    if IS_WINDOWS:
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["/bin/bash", "-c", command]
    try:
        proc = subprocess.run(
            argv,
            cwd=wd,
            capture_output=True,
            text=True,
            timeout=max(5, min(timeout, 300)),
        )
    except subprocess.TimeoutExpired:
        _audit("run_command", f"TIMEOUT: {command[:120]}")
        return {"status": "error", "error": f"timed out after {timeout}s"}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    out, errput = proc.stdout[-4000:], proc.stderr[-2000:]
    _audit("run_command", f"rc={proc.returncode}: {command[:120]}")
    return {
        "status": "ok",
        "returncode": proc.returncode,
        "stdout": out,
        "stderr": errput,
    }


def open_with_default_app(target: str) -> dict:
    """Open a URL in the default browser, or a file in its default app
    (VS Code, Excel, Photos, ...). ALWAYS blocks on human approval — it acts
    visibly on the founder's machine, so the founder sees WHAT before it opens.
    """
    emit("tool_call", _agent(), f"open_with_default_app {target[:80]}")
    target = (target or "").strip()
    if not target:
        return {"status": "error", "error": "empty target"}
    is_url = target.startswith(("http://", "https://"))
    path = target
    if not is_url:
        p, err = _resolve(target)
        if err:
            return {"status": "error", "error": err}
        if not os.path.exists(p):
            return {"status": "error", "error": "not found"}
        if _is_secret(p):
            return {"status": "blocked", "error": "credential files stay closed"}
        path = p
    ok = request_approval(
        {
            "kind": "open-app",
            "summary": f"Open with default app: {target[:200]}",
            "payload": {"target": target[:500]},
        }
    )
    if not ok:
        return {"status": "denied", "error": "human denied (or timed out) the open"}
    try:
        if IS_WINDOWS and hasattr(os, "startfile"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], timeout=15)
        else:
            subprocess.run(["xdg-open", path], timeout=15)
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    _audit("open_with_default_app", f"APPROVED open: {target[:120]}")
    return {"status": "ok", "opened": target}


_TOOLS = [list_dir, read_file, write_file, delete_file, run_command,
          open_with_default_app]

if FastMCP is not None:
    mcp = FastMCP("local")
    for _fn in _TOOLS:
        mcp.tool()(_fn)


if __name__ == "__main__":
    if FastMCP is None:
        raise SystemExit("mcp package not installed; plain functions still importable for tests")
    mcp.run()
