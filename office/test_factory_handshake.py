"""Factory handshake tests — deterministic, no network, no model calls.

Pins the provisioning handshake on top of the lease desk: when a live
lease (trial running, or converted) is read through /api/lease/{id}, the
platform seats the agent — an instance materialises in
office/lease_instances.json (a tmp path here), built ONLY from the
sanitised projection's spec fields. Reads are idempotent, a changed spec
reseats the instance in place, the lease's end is mirrored
(trial ended -> "returned", closed -> "closed"), a not-yet-active lease
seats nothing, and a failed Store fetch materialises nothing and keeps
the desk's plain error behaviour.

The Store fetch, the gate's ID verdict, and the instance store's path are
stubbed at the module seams, the same way test_lease_desk.py isolates
the desk.

Run: pytest office/test_factory_handshake.py   (needs fastapi + httpx)
"""

import importlib.util
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _stub(name: str, **attrs):
    mod = types.ModuleType(name)
    for key, val in attrs.items():
        setattr(mod, key, val)
    sys.modules[name] = mod


# The handshake never touches chat machinery; keep the import hermetic.
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
COOKIE = {"ansai_id_session": "tok"}


def _signed_in(monkeypatch):
    monkeypatch.setattr(server, "_id_person", lambda token: PERSON if token else None)


def _fresh_instances(monkeypatch, tmp_path):
    """Point the instance store at a throwaway file, empty in memory."""
    path = tmp_path / "lease_instances.json"
    monkeypatch.setattr(server, "LEASE_INSTANCES_PATH", str(path))
    monkeypatch.setattr(server, "_instances", {})
    return path


def _record(status="trial_active", per_txn_cap=2000) -> dict:
    """A Store record shaped like the real one — including the internal
    fields that must never reach the instance or the response."""
    started = (datetime.now(timezone.utc) - timedelta(days=2, hours=3)).isoformat()
    ends = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    return {
        "id": "rec-test-1",
        "jobId": "bookkeeper",
        "status": status,
        "createdAt": started,
        "updatedAt": started,
        "renter": {
            "id": "ansai-id:abc",
            "name": "Zawadi",
            "email": "zawadi@example.com",
            "phone": "+254700000000",
            "id_document_number": "12345678",
        },
        "answers": {"businessName": "SECRET-ANSWER"},
        "audit": [{"seq": 1, "event": "SECRET-AUDIT"}],
        "spec": {
            "identity": {"name": "bookkeeper-agent-zawadi", "purpose": "Books reconciled monthly."},
            "policy": {
                "may": ["read statements and receipts"],
                "must_approve": ["locking a month"],
                "never": ["invent a figure"],
            },
            "wallet": {
                "daily_cap": 10000,
                "daily_cap_unit": "KES/day",
                "per_txn_cap": per_txn_cap,
                "approval_threshold_kes": 0,
                "allowed_payees": ["KPLC Prepaid", "Naivas"],
            },
        },
        "pricing": {"model": "subscription", "totalKes": 777777},
        "voice": {"preset": "calm", "samples": ["Karibu sana — your books are ready."]},
        "trial": {"startedAt": started, "endsAt": ends, "retentionUntil": None, "packs": []},
    }


def _serve(monkeypatch, record):
    monkeypatch.setattr(server, "_fetch_store_record", lambda rid, cookie: record)


# --- materialisation ----------------------------------------------------------


def test_first_read_of_trial_record_seats_the_agent(monkeypatch, tmp_path):
    _signed_in(monkeypatch)
    path = _fresh_instances(monkeypatch, tmp_path)
    _serve(monkeypatch, _record())
    res = client.get("/api/lease/rec-test-1", cookies=COOKIE)
    assert res.status_code == 200
    inst = res.json()["instance"]
    assert inst is not None
    assert inst["record_id"] == "rec-test-1"
    assert inst["template"] == "bookkeeper"
    assert inst["agent_name"] == "bookkeeper-agent-zawadi"
    assert inst["status"] == "seated"
    assert inst["spec"]["wallet"] == {
        "perTxnCapKes": 2000,
        "dailyCap": 10000,
        "dailyCapUnit": "KES/day",
        "approvalThresholdKes": 0,
        "allowedPayees": ["KPLC Prepaid", "Naivas"],
    }
    assert inst["spec"]["guardrails"] == {
        "may": ["read statements and receipts"],
        "mustApprove": ["locking a month"],
        "never": ["invent a figure"],
    }
    assert inst["spec"]["voice"] == {"presetName": "Calm & clear", "sampleCount": 1}
    assert len(inst["spec_hash"]) == 64
    assert inst["created_at"] == inst["updated_at"]
    # Persisted to the instance store, keyed by record id.
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert list(on_disk.keys()) == ["rec-test-1"]
    assert on_disk["rec-test-1"]["spec_hash"] == inst["spec_hash"]
    # Nothing internal crossed into the instance or the response.
    for marker in ("zawadi@example.com", "+254700000000", "12345678",
                   "SECRET-ANSWER", "SECRET-AUDIT", "777777"):
        assert marker not in res.text, marker


def test_converted_record_is_seated_too(monkeypatch, tmp_path):
    _signed_in(monkeypatch)
    _fresh_instances(monkeypatch, tmp_path)
    _serve(monkeypatch, _record(status="converted"))
    res = client.get("/api/lease/rec-test-1", cookies=COOKIE)
    assert res.status_code == 200
    assert res.json()["instance"]["status"] == "seated"


def test_second_read_does_not_duplicate(monkeypatch, tmp_path):
    _signed_in(monkeypatch)
    path = _fresh_instances(monkeypatch, tmp_path)
    _serve(monkeypatch, _record())
    first = client.get("/api/lease/rec-test-1", cookies=COOKIE).json()["instance"]
    second = client.get("/api/lease/rec-test-1", cookies=COOKIE).json()["instance"]
    assert second == first  # same instance, untouched timestamps and hash
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert list(on_disk.keys()) == ["rec-test-1"]
    # And a restart restores it instead of reseating: clear memory, reload
    # from disk, read again — created_at must be the original.
    monkeypatch.setattr(server, "_instances", {})
    server._load_instances()
    third = client.get("/api/lease/rec-test-1", cookies=COOKIE).json()["instance"]
    assert third["created_at"] == first["created_at"]
    assert third["spec_hash"] == first["spec_hash"]


def test_spec_change_reseats_in_place(monkeypatch, tmp_path):
    _signed_in(monkeypatch)
    _fresh_instances(monkeypatch, tmp_path)
    clock = {"t": "2026-11-21T09:00:00+00:00"}
    monkeypatch.setattr(server, "_now", lambda: clock["t"])
    record = _record(per_txn_cap=2000)
    _serve(monkeypatch, record)
    first = client.get("/api/lease/rec-test-1", cookies=COOKIE).json()["instance"]
    assert first["created_at"] == "2026-11-21T09:00:00+00:00"

    clock["t"] = "2026-11-21T10:00:00+00:00"
    record["spec"]["wallet"]["per_txn_cap"] = 3000  # the setup changed in the Store
    second = client.get("/api/lease/rec-test-1", cookies=COOKIE).json()["instance"]
    assert second["spec"]["wallet"]["perTxnCapKes"] == 3000
    assert second["spec_hash"] != first["spec_hash"]
    assert second["created_at"] == first["created_at"]       # same seat
    assert second["updated_at"] == "2026-11-21T10:00:00+00:00"  # bumped


# --- what does NOT seat -------------------------------------------------------


def test_no_instance_until_the_lease_activates(monkeypatch, tmp_path):
    _signed_in(monkeypatch)
    path = _fresh_instances(monkeypatch, tmp_path)
    for status in ("provisioning", "awaiting_payment"):
        _serve(monkeypatch, _record(status=status))
        res = client.get("/api/lease/rec-test-1", cookies=COOKIE)
        assert res.status_code == 200
        assert res.json()["instance"] is None, status
    assert not path.exists()  # the store is only created on first use


def test_failed_store_fetch_materialises_nothing(monkeypatch, tmp_path):
    _signed_in(monkeypatch)
    path = _fresh_instances(monkeypatch, tmp_path)

    def miss(rid, cookie):
        raise server._StoreMiss()

    monkeypatch.setattr(server, "_fetch_store_record", miss)
    res = client.get("/api/lease/rec-nope", cookies=COOKIE)
    assert res.status_code == 404
    assert res.json()["error"] == "not_found"

    def down(rid, cookie):
        raise server._StoreDown()

    monkeypatch.setattr(server, "_fetch_store_record", down)
    res = client.get("/api/lease/rec-test-1", cookies=COOKIE)
    assert res.status_code == 502
    assert res.json()["error"] == "store_unreachable"

    assert not path.exists()
    assert server._instances == {}


# --- the lease's end, mirrored -------------------------------------------------


def test_instance_mirrors_the_leases_end(monkeypatch, tmp_path):
    _signed_in(monkeypatch)
    _fresh_instances(monkeypatch, tmp_path)
    record = _record(status="trial_active")
    _serve(monkeypatch, record)
    seated = client.get("/api/lease/rec-test-1", cookies=COOKIE).json()["instance"]
    assert seated["status"] == "seated"

    record["status"] = "trial_expired"  # the free week ended unconverted
    res = client.get("/api/lease/rec-test-1", cookies=COOKIE)
    assert res.json()["state"]["label"] == "Trial ended"
    returned = res.json()["instance"]
    assert returned["status"] == "returned"
    assert returned["created_at"] == seated["created_at"]

    record["status"] = "closed"
    res = client.get("/api/lease/rec-test-1", cookies=COOKIE)
    assert res.json()["instance"]["status"] == "closed"


def test_desk_page_shows_the_platform_section(monkeypatch, tmp_path):
    _signed_in(monkeypatch)
    res = client.get("/lease/rec-test-1", cookies=COOKIE)
    assert res.status_code == 200
    assert "On the platform" in res.text
    assert "seats itself here when the lease activates" in res.text
