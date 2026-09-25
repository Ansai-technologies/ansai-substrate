"""Layer 1 — deterministic tests.

No model calls, no network. These pin the contracts everything else builds on:
MCP stub shapes, the handoff contract, and the approval queue mechanics.
Run: pytest evals/test_tools.py
"""

import importlib.util
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "agents"))
sys.path.insert(0, os.path.join(ROOT, "policy"))


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


whatsapp_server = _load("whatsapp_server", os.path.join(ROOT, "mcp", "whatsapp", "server.py"))
mpesa_server = _load("mpesa_server", os.path.join(ROOT, "mcp", "mpesa", "server.py"))
web_server = _load("web_server", os.path.join(ROOT, "mcp", "web", "server.py"))

from handoff import summarize_state, validate_summary, SUMMARY_BUDGET  # noqa: E402


def test_whatsapp_send_stub_contract():
    out = whatsapp_server.send_message(to="+254700000000", body="hello")
    assert out["status"] == "stub"
    assert out["to"] == "+254700000000"
    assert "no real message sent" in out["note"]


def test_whatsapp_read_stub_contract():
    out = whatsapp_server.read_messages(conversation_id="conv-1")
    assert out["status"] == "stub"
    assert out["conversation_id"] == "conv-1"
    assert isinstance(out["messages"], list)


def test_mpesa_balance_stub_contract():
    out = mpesa_server.get_balance(account="sacco-float")
    assert out["status"] == "stub"
    assert "no real query" in out["note"]


def test_mpesa_stk_push_stub_contract():
    out = mpesa_server.stk_push(phone="+254700000000", amount_kes=500, reference="t1")
    assert out["status"] == "stub"
    assert out["amount_kes"] == 500
    assert "no real push" in out["note"]


def test_handoff_contract_keys_and_budget():
    transcript = "user: my name is Achieng\nagent: confirmed, Achieng. ID number?\n" * 200
    s = summarize_state(transcript, goal="onboard member")
    assert validate_summary(s)
    assert set(s.keys()) == {"goal", "facts", "open_questions", "proposed_next"}
    assert len(json.dumps(s)) <= SUMMARY_BUDGET


def test_handoff_rejects_bad_shape():
    assert not validate_summary({"goal": "x"})
    assert not validate_summary(
        {"goal": "x", "facts": [], "open_questions": [], "proposed_next": "y", "extra": 1}
    )


def test_approval_queue_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPROVAL_QUEUE", str(tmp_path / "q.jsonl"))
    import importlib
    import approvals

    importlib.reload(approvals)  # re-read QUEUE_PATH from the patched env
    assert approvals.list_pending() == []
    assert approvals.approve("missing") is False
    assert approvals.deny("missing") is False
    # request_approval() blocks on human input — exercised manually, not here.


# ---------------------------------------------------------------------------
# GitHub tools: no token -> clean error, no network attempted.
# ---------------------------------------------------------------------------

def _load_github():
    return _load("github_server", os.path.join(ROOT, "mcp", "github", "server.py"))


def test_github_missing_token_is_error_not_exception(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    g = _load_github()
    assert g.list_repos()["status"] == "error"
    assert "GITHUB_TOKEN" in g.list_repos()["error"]
    assert g.read_file("o/r", "README.md")["status"] == "error"


def test_github_rejects_bad_repo_format(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    g = _load_github()
    out = g.read_file("not-a-repo", "README.md")
    assert out["status"] == "error" and "owner/name" in out["error"]


def test_github_writes_deny_without_approval(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    g = _load_github()
    monkeypatch.setattr(g, "request_approval", lambda *a, **k: False)
    out = g.create_issue("o/r", "title", "body")
    assert out["status"] == "denied"
    out = g.comment_on_issue("o/r", 1, "hi")
    assert out["status"] == "denied"


# ---------------------------------------------------------------------------
# Web tools: pure parsing functions, no network.
# ---------------------------------------------------------------------------

_DDG_FIXTURE = """
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&amp;rut=1">Alpha result</a>
<a class="result__snippet" href="x">first snippet here</a>
<a rel="nofollow" class="result__a" href="https://example.org/b">Beta result</a>
<a class="result__snippet" href="x">second snippet</a>
"""

_HTML_FIXTURE = """
<html><head><title>Test Page</title><style>.x{color:red}</style></head>
<body><script>var a=1;</script><h1>Hello</h1><p>world &amp; friends</p></body></html>
"""


def test_web_parse_ddg_results():
    out = web_server.parse_ddg_results(_DDG_FIXTURE, limit=5)
    assert len(out) == 2
    assert out[0]["url"] == "https://example.com/a"
    assert out[0]["title"] == "Alpha result"
    assert out[0]["snippet"] == "first snippet here"
    assert out[1]["url"] == "https://example.org/b"


def test_web_html_to_text_strips_noise():
    out = web_server.html_to_text(_HTML_FIXTURE)
    assert out["title"] == "Test Page"
    assert "Hello" in out["text"] and "world & friends" in out["text"]
    assert "var a=1" not in out["text"] and ".x{color:red}" not in out["text"]


def test_web_fetch_rejects_non_http():
    out = web_server.fetch_page("ftp://example.com/x")
    assert out["status"] == "error"


# ---------------------------------------------------------------------------
# Local tools: sandbox, secrets, allowlist — no real shell, no network.
# ---------------------------------------------------------------------------

def _load_local(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_LOCAL_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    return _load("local_server", os.path.join(ROOT, "mcp", "local", "server.py"))


def test_local_read_write_inside_sandbox(tmp_path, monkeypatch):
    local = _load_local(tmp_path, monkeypatch)
    assert local.write_file("note.txt", "hello")["status"] == "ok"
    out = local.read_file("note.txt")
    assert out["status"] == "ok" and out["text"] == "hello"
    entries = local.list_dir(".")["entries"]
    assert any(e["name"] == "note.txt" for e in entries)


def test_local_blocks_path_traversal(tmp_path, monkeypatch):
    local = _load_local(tmp_path, monkeypatch)
    out = local.read_file("../outside.txt")
    assert out["status"] == "error" and "sandbox" in out["error"]


def test_local_refuses_secret_files(tmp_path, monkeypatch):
    local = _load_local(tmp_path, monkeypatch)
    (tmp_path / ".env").write_text("KEY=abc")
    out = local.read_file(".env")
    assert out["status"] == "blocked"


def test_local_write_outside_needs_approval_denied(tmp_path, monkeypatch):
    local = _load_local(tmp_path, monkeypatch)
    monkeypatch.setattr(local, "request_approval", lambda *a, **k: False)
    out = local.write_file("/tmp/definitely-outside-x.txt", "x")
    assert out["status"] == "denied"


def test_local_delete_always_asks(tmp_path, monkeypatch):
    local = _load_local(tmp_path, monkeypatch)
    (tmp_path / "gone.txt").write_text("x")
    monkeypatch.setattr(local, "request_approval", lambda *a, **k: False)
    assert local.delete_file("gone.txt")["status"] == "denied"
    assert (tmp_path / "gone.txt").exists()  # denied = untouched


def test_local_shell_allowlist():
    local = _load("local_server_ro", os.path.join(ROOT, "mcp", "local", "server.py"))
    assert local.is_allowlisted("git status")
    assert local.is_allowlisted("  ls -la  ")
    assert not local.is_allowlisted("rm -rf /")
    assert not local.is_allowlisted("cat .env")
    assert not local.is_allowlisted("echo hi && rm x")
    assert not local.is_allowlisted("git status | tee out.txt")


def test_local_open_app_asks_approval(tmp_path, monkeypatch):
    local = _load_local(tmp_path, monkeypatch)
    (tmp_path / "doc.txt").write_text("x")
    monkeypatch.setattr(local, "request_approval", lambda *a, **k: False)
    out = local.open_with_default_app("doc.txt")
    assert out["status"] == "denied"
    out = local.open_with_default_app("https://example.com")
    assert out["status"] == "denied"
    assert local.open_with_default_app("")["status"] == "error"
    assert local.open_with_default_app("missing.txt")["status"] == "error"
