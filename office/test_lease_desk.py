"""Lease desk tests — deterministic, no network, no model calls.

Pins the /lease/{record_id} desk: the page serves behind the Ansai ID gate
(signed-out pages redirect, signed-out API calls 401, /api/health stays
exempt), /api/lease/{id} proxies the Store record with only the caller's
session cookies forwarded, the relayed projection is sanitised (no renter
PII, answers, audit trail, or wallet snapshots), and Store failures become
plain JSON errors (404 not-found, 502 unreachable) — never a white screen
or an unhandled 500.

The Store fetch and the gate's ID verdict are stubbed at the module seam,
the same way the gate behaviour test isolated the app from the live ID
service. The office's heavy chat imports (mini_agent, tools_registry,
events) are stubbed too: the desk needs none of them.

Run: pytest office/test_lease_desk.py   (needs fastapi + httpx installed)
"""

import importlib.util
import json
import os
import sys
import types
import urllib.error
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _stub(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, val in attrs.items():
        setattr(mod, key, val)
    sys.modules[name] = mod


# The desk never touches chat machinery; keep the import hermetic.
_stub("mini_agent", build_mini_agent=lambda *a, **k: None)
_stub("tools_registry", get_tools=lambda *a, **k: [])
_stub("events", emit=lambda *a, **k: None)


def _load_server():
    spec = importlib.util.spec_from_file_location(
        "office_server", os.path.join(ROOT, "office", "server.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


server = _load_server()

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(server.app, follow_redirects=False)

PERSON = {"id": "person-1", "full_name": "Test Person"}


def _signed_in(monkeypatch):
    monkeypatch.setattr(server, "_id_person", lambda token: PERSON if token else None)


def _signed_out(monkeypatch):
    monkeypatch.setattr(server, "_id_person", lambda token: None)


def _fixture_record() -> dict:
    """A trial-active Bookkeeper record, shaped like the Store's real one —
    including the internal fields the projection must never relay."""
    started = (datetime.now(timezone.utc) - timedelta(days=2, hours=3)).isoformat()
    ends = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    return {
        "id": "rec-test-1",
        "jobId": "bookkeeper",
        "status": "trial_active",
        "createdAt": started,
        "updatedAt": started,
        "renter": {
            "id": "ansai-id:abc",
            "name": "Zawadi",
            "email": "zawadi@example.com",
            "phone": "+254700000000",
            "id_document_number": "12345678",
            "kyc_status": "verified",
        },
        "customer": {"name": "Zawadi", "phone": "+254700000000", "email": "zawadi@example.com"},
        "answers": {"businessName": "SECRET-ANSWER"},
        "audit": [{"seq": 1, "event": "SECRET-AUDIT"}],
        "spec": {
            "identity": {"name": "bookkeeper-agent-zawadi", "purpose": "Books reconciled monthly."},
            "policy": {
                "may": ["read statements and receipts"],
                "must_approve": ["locking a month"],
                "never": ["invent a figure"],
                "data_access": ["statements"],
            },
            "wallet": {
                "daily_cap": 10000,
                "daily_cap_unit": "KES/day",
                "per_txn_cap": 2000,
                "approval_threshold_kes": 0,
                "allowed_payees": ["KPLC Prepaid", "Naivas"],
            },
        },
        "pricing": {"model": "subscription", "totalKes": 777777},
        "voice": {"preset": "calm", "samples": ["Karibu sana — your books are ready."]},
        "trial": {
            "startedAt": started,
            "endsAt": ends,
            "retentionUntil": None,
            "paidWallet": {"daily_cap": 999999, "approval_threshold_kes": 555555},
            "packs": [
                {
                    "trigger": "trial_end",
                    "generated_at": ends,
                    "period": {"from": started, "to": ends},
                    "totals": {
                        "actions": 9,
                        "approvalsAsked": 2,
                        "approvalsApproved": 2,
                        "approvalsDenied": 0,
                        "walletMovedKes": 4500,
                    },
                    "signature": {"alg": "sha256", "hash": "f00df00df00df00d" + "a" * 48},
                    "actions": [{"event": "SECRET-AUDIT"}],
                    "renter": {"id": "x", "name": "Zawadi"},
                }
            ],
        },
    }


# --- the page, behind the gate ------------------------------------------------


def test_lease_page_serves_desk_html(monkeypatch):
    _signed_in(monkeypatch)
    res = client.get("/lease/rec-test-1", cookies={"ansai_id_session": "tok"})
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Your agent's desk" in res.text
    assert "/api/lease/" in res.text


def test_lease_page_signed_out_redirects_to_sign_in(monkeypatch):
    _signed_out(monkeypatch)
    res = client.get("/lease/rec-test-1")
    assert res.status_code == 302
    assert res.headers["location"] == server.ID_BASE + "/home.html"


def test_lease_api_signed_out_is_401(monkeypatch):
    _signed_out(monkeypatch)
    res = client.get("/api/lease/rec-test-1")
    assert res.status_code == 401
    assert res.json() == {"ok": False, "error": "ansai_id_required"}


def test_health_stays_exempt_signed_out(monkeypatch):
    _signed_out(monkeypatch)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True


# --- the proxy + projection ---------------------------------------------------


def test_lease_api_returns_sanitised_projection(monkeypatch):
    _signed_in(monkeypatch)
    monkeypatch.setattr(server, "_fetch_store_record", lambda rid, cookie: _fixture_record())
    res = client.get("/api/lease/rec-test-1", cookies={"ansai_id_session": "tok"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["id"] == "rec-test-1"
    assert data["kind"] == "The Bookkeeper"
    assert data["agentName"] == "bookkeeper-agent-zawadi"
    assert data["state"]["label"] == "On trial"
    assert data["state"]["detail"] == "day 3 of 7"  # started 2 days 3h ago
    assert data["wallet"] == {
        "perTxnCapKes": 2000,
        "dailyCap": 10000,
        "dailyCapUnit": "KES/day",
        "approvalThresholdKes": 0,
        "allowedPayees": ["KPLC Prepaid", "Naivas"],
    }
    assert data["guardrails"] == {
        "may": ["read statements and receipts"],
        "mustApprove": ["locking a month"],
        "never": ["invent a figure"],
    }
    assert data["voice"] == {"presetName": "Calm & clear", "sampleCount": 1}
    assert len(data["statements"]) == 1
    pack = data["statements"][0]
    assert pack["label"] == "End-of-trial statement"
    assert pack["actions"] == 9
    assert pack["approvalsAsked"] == 2
    assert pack["walletMovedKes"] == 4500
    assert pack["ref"] == "f00df00df00df00d"
    # Exactly the projection's keys — nothing else crosses.
    assert set(data.keys()) == {
        "ok", "id", "kind", "agentName", "purpose", "state", "trialEndsAt",
        "recordsUntil", "wallet", "guardrails", "voice", "statements", "createdAt",
    }


def test_projection_drops_internal_fields(monkeypatch):
    _signed_in(monkeypatch)
    monkeypatch.setattr(server, "_fetch_store_record", lambda rid, cookie: _fixture_record())
    res = client.get("/api/lease/rec-test-1", cookies={"ansai_id_session": "tok"})
    text = res.text
    for marker in (
        "zawadi@example.com",   # renter email
        "+254700000000",        # renter/customer phone
        "12345678",             # ID document number
        "SECRET-ANSWER",        # setup answers
        "SECRET-AUDIT",         # audit trail (record-level and inside the pack)
        "999999",               # paid-wallet snapshot daily cap
        "555555",               # paid-wallet snapshot threshold
        "777777",               # pricing internals
        "data_access",          # raw spec field name
        "paidWallet",
    ):
        assert marker not in text, marker


def test_store_miss_becomes_plain_404(monkeypatch):
    _signed_in(monkeypatch)

    def miss(rid, cookie):
        raise server._StoreMiss()

    monkeypatch.setattr(server, "_fetch_store_record", miss)
    res = client.get("/api/lease/rec-nope", cookies={"ansai_id_session": "tok"})
    assert res.status_code == 404
    body = res.json()
    assert body["ok"] is False
    assert body["error"] == "not_found"
    assert "couldn't find that agent" in body["message"]


def test_store_down_becomes_plain_502(monkeypatch):
    _signed_in(monkeypatch)

    def down(rid, cookie):
        raise server._StoreDown()

    monkeypatch.setattr(server, "_fetch_store_record", down)
    res = client.get("/api/lease/rec-test-1", cookies={"ansai_id_session": "tok"})
    assert res.status_code == 502
    body = res.json()
    assert body["ok"] is False
    assert body["error"] == "store_unreachable"
    assert body["message"]


# --- the Store fetch itself ---------------------------------------------------


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_fetch_forwards_cookies_id_and_timeout(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["cookie"] = req.headers.get("Cookie")
        seen["timeout"] = timeout
        return _FakeResponse({"record": {"id": "rec x", "jobId": "shop"}})

    monkeypatch.setattr(server.urllib.request, "urlopen", fake_urlopen)
    record = server._fetch_store_record("rec x", "ansai_id_session=tok1; as_session=tok2")
    assert record["id"] == "rec x"
    assert seen["url"] == server.STORE_BASE + "/api/provision?id=rec%20x"
    assert seen["cookie"] == "ansai_id_session=tok1; as_session=tok2"
    assert seen["timeout"] == 4


def test_fetch_maps_store_statuses(monkeypatch):
    def raising(code):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, code, "err", None, None)

        return fake_urlopen

    for code, exc_type in ((404, server._StoreMiss), (401, server._StoreMiss),
                           (403, server._StoreMiss), (500, server._StoreDown)):
        monkeypatch.setattr(server.urllib.request, "urlopen", raising(code))
        try:
            server._fetch_store_record("rec-1", "ansai_id_session=tok")
        except exc_type:
            pass
        else:
            raise AssertionError(f"Store {code} should raise {exc_type.__name__}")

    def timeout_urlopen(req, timeout=None):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(server.urllib.request, "urlopen", timeout_urlopen)
    try:
        server._fetch_store_record("rec-1", "ansai_id_session=tok")
    except server._StoreDown:
        pass
    else:
        raise AssertionError("a Store timeout should raise _StoreDown")


def test_cookie_header_forwards_only_the_two_session_cookies():
    class FakeRequest:
        cookies = {"ansai_id_session": "a", "as_session": "b", "other": "zzz", "theme": "dark"}

    header = server._store_cookie_header(FakeRequest())
    assert header == "ansai_id_session=a; as_session=b"


# --- plain-language lease states ----------------------------------------------


def test_lease_state_words():
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    cases = {
        "converted": "Active",
        "paused": "Paused",
        "closed": "Closed",
        "provisioning": "Setting up",
        "trial_expired": "Trial ended",
        "awaiting_payment": "Not started",
    }
    for status, label in cases.items():
        state = server._lease_state({"status": status}, now)
        assert state["label"] == label, status
    trial = server._lease_state(
        {"status": "trial_active", "trial": {"startedAt": "2026-11-18T12:00:00+00:00"}}, now
    )
    assert trial["label"] == "On trial"
    assert trial["detail"] == "day 3 of 7"
