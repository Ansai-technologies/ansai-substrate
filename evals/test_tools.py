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


def test_mpesa_balance_stub_contract(monkeypatch):
    monkeypatch.delenv("DARAJA_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("DARAJA_CONSUMER_SECRET", raising=False)
    out = mpesa_server.get_balance(account="sacco-float")
    assert out["status"] == "stub"
    assert "no real query" in out["note"]


def test_mpesa_stk_push_stub_contract(monkeypatch):
    monkeypatch.delenv("DARAJA_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("DARAJA_CONSUMER_SECRET", raising=False)
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

# ---------------------------------------------------------------------------
# M-Pesa Daraja wiring: pure helpers + HITL gating. No network in tests.
# ---------------------------------------------------------------------------


def _mpesa_with_keys(monkeypatch):
    monkeypatch.setenv("DARAJA_CONSUMER_KEY", "fake-key")
    monkeypatch.setenv("DARAJA_CONSUMER_SECRET", "fake-secret")
    monkeypatch.setenv("DARAJA_PASSKEY", "fake-passkey")
    # reset the in-memory token cache between tests
    mpesa_server._token_cache["token"] = None
    mpesa_server._token_cache["expires_at"] = 0.0


def test_mpesa_normalize_phone_formats():
    assert mpesa_server.normalize_phone("0722000000") == "254722000000"
    assert mpesa_server.normalize_phone("254722000000") == "254722000000"
    assert mpesa_server.normalize_phone("+254722000000") == "254722000000"
    assert mpesa_server.normalize_phone("0722 000 000") == "254722000000"


def test_mpesa_normalize_phone_rejects_garbage():
    import pytest

    for bad in ("123", "07123", "+15551234567", "not-a-number", ""):
        with pytest.raises(ValueError):
            mpesa_server.normalize_phone(bad)


def test_mpesa_stk_password_is_base64_concat():
    import base64

    pw = mpesa_server.stk_password("174379", "passkey", "20260101000000")
    assert pw == base64.b64encode(b"174379passkey20260101000000").decode()


def test_mpesa_sandbox_only_no_production_switch():
    assert "sandbox.safaricom.co.ke" in mpesa_server.STK_PUSH_URL
    assert "sandbox.safaricom.co.ke" in mpesa_server.TOKEN_URL
    src = open(mpesa_server.__file__).read()
    assert "api.safaricom.co.ke" not in src  # production host must not appear


def test_mpesa_balance_with_keys_needs_phase0b(monkeypatch):
    _mpesa_with_keys(monkeypatch)
    out = mpesa_server.get_balance(account="x")
    assert out["status"] == "error"
    assert "Phase 0b" in out["error"]


def test_mpesa_stk_push_denied_sends_nothing(monkeypatch):
    _mpesa_with_keys(monkeypatch)
    monkeypatch.setattr(mpesa_server, "request_approval", lambda *a, **k: False)
    called = []
    monkeypatch.setattr(
        mpesa_server, "_post_json", lambda *a, **k: called.append(1) or {}
    )
    out = mpesa_server.stk_push(phone="0722000000", amount_kes=500, reference="t9")
    assert out["status"] == "denied"
    assert called == []  # denied = no HTTP attempted


def test_mpesa_stk_push_approved_posts_sandbox(monkeypatch):
    _mpesa_with_keys(monkeypatch)
    seen = {}

    def fake_approval(action, timeout=3600):
        seen["action"] = action
        return True

    def fake_post(url, body, token):
        seen["url"] = url
        seen["body"] = body
        return {
            "ResponseCode": "0",
            "CheckoutRequestID": "ws_CO_1",
            "CustomerMessage": "Success",
        }

    monkeypatch.setattr(mpesa_server, "request_approval", fake_approval)
    monkeypatch.setattr(mpesa_server, "_post_json", fake_post)
    monkeypatch.setattr(mpesa_server, "_get_token", lambda: "tok")
    out = mpesa_server.stk_push(phone="+254722000000", amount_kes=1500, reference="order-42")
    assert out["status"] == "ok"
    assert out["checkout_request_id"] == "ws_CO_1"
    assert "sandbox.safaricom.co.ke" in seen["url"]
    body = seen["body"]
    assert body["PartyA"] == "254722000000"
    assert body["Amount"] == 1500
    assert body["BusinessShortCode"] == "174379"
    # HITL saw a human-readable summary before anything was sent
    assert "1500" in seen["action"]["summary"] and "254722000000" in seen["action"]["summary"]


def test_mpesa_stk_push_rejects_bad_input(monkeypatch):
    _mpesa_with_keys(monkeypatch)
    monkeypatch.setattr(mpesa_server, "request_approval", lambda *a, **k: True)
    out = mpesa_server.stk_push(phone="123", amount_kes=500, reference="t")
    assert out["status"] == "error"
    out = mpesa_server.stk_push(phone="0722000000", amount_kes=0, reference="t")
    assert out["status"] == "error"


def test_mpesa_stk_push_needs_passkey(monkeypatch):
    monkeypatch.setenv("DARAJA_CONSUMER_KEY", "fake-key")
    monkeypatch.setenv("DARAJA_CONSUMER_SECRET", "fake-secret")
    monkeypatch.delenv("DARAJA_PASSKEY", raising=False)
    out = mpesa_server.stk_push(phone="0722000000", amount_kes=500, reference="t")
    assert out["status"] == "error"
    assert "DARAJA_PASSKEY" in out["error"]
