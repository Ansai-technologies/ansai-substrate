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
