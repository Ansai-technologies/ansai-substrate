"""Customer platform home tests — deterministic, no network, no model calls.

Pins the /home platform home (the founder's Store spec SS9: all of a
customer's agents live together on one home; each card opens its desk;
"Add another agent" goes back to the Store in a new tab) and the
customer-route Google admission: a Store-verified Google session
(as_google, checked server-side against the Store's /api/session) opens
the customer routes ONLY — /home, /api/home, /lease/*, /api/lease/* —
while /, /platform and every other route stay Ansai-ID-only.

The Store fetches and both gate verdicts are stubbed at the module seam,
the same way the lease desk tests isolate the app.

Run: pytest office/test_platform_home.py   (needs fastapi + httpx installed)
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
GOOGLE_PERSON = {"full_name": "Google Person", "email": "gperson@example.com"}


def _id_in(monkeypatch):
    monkeypatch.setattr(server, "_id_person", lambda token: PERSON if token else None)


def _id_out(monkeypatch):
    monkeypatch.setattr(server, "_id_person", lambda token: None)


def _google_in(monkeypatch):
    monkeypatch.setattr(
        server, "_google_person", lambda cookie: GOOGLE_PERSON if cookie else None
    )


def _google_out(monkeypatch):
    monkeypatch.setattr(server, "_google_person", lambda cookie: None)


def _signed_out(monkeypatch):
    _id_out(monkeypatch)
    _google_out(monkeypatch)


def _fixture_list_items() -> list:
    """Store list items, shaped like GET /api/provision's records — plus the
    internal fields the home projection must never relay."""
    ends = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    created = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    return [
        {
            "id": "rec-test-1",
            "jobId": "bookkeeper",
            "status": "trial_active",
            "createdAt": created,
            "trialEndsAt": ends,
            "agentName": "bookkeeper-agent-zawadi",
            "answers": {"businessName": "Zawadi Crafts"},
            "customer": {
                "name": "Zawadi",
                "email": "zawadi@example.com",
                "phone": "+254700000000",
            },
            "renter": {"id": "ansai-id:abc", "email": "zawadi@example.com"},
            "totalKes": 777777,
            "foundation": "SECRET-FOUNDATION",
            "accountable_operator": {"email": "op@example.com"},
        },
        {
            "id": "rec-test-2",
            "jobId": "shop",
            "status": "converted",
            "createdAt": created,
            "trialEndsAt": None,
            "agentName": "shop-agent-zawadi",
            "answers": {"businessName": "Zawadi Crafts"},
        },
    ]


# --- the page, behind the gate -------------------------------------------------


def test_home_page_serves_html(monkeypatch):
    _id_in(monkeypatch)
    _google_out(monkeypatch)
    res = client.get("/home", cookies={"ansai_id_session": "tok"})
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Your agents" in res.text
    assert "/api/home" in res.text
    # "Add another agent" goes to the Store shelf, in a new tab.
    assert 'href="https://store.ansaitechnologies.co.ke"' in res.text
    assert 'target="_blank"' in res.text
    assert "Add another agent" in res.text
    assert "No agents yet" in res.text  # the honest empty state ships in the page


def test_home_page_signed_out_redirects_to_sign_in(monkeypatch):
    _signed_out(monkeypatch)
    res = client.get("/home")
    assert res.status_code == 302
    assert res.headers["location"] == server.ID_BASE + "/home.html"


def test_home_api_signed_out_is_401(monkeypatch):
    _signed_out(monkeypatch)
    res = client.get("/api/home")
    assert res.status_code == 401
    assert res.json() == {"ok": False, "error": "ansai_id_required"}


# --- the list proxy + projection ------------------------------------------------


def test_home_api_returns_projected_agents(monkeypatch):
    _id_in(monkeypatch)
    _google_out(monkeypatch)
    monkeypatch.setattr(server, "_fetch_store_records", lambda cookie: _fixture_list_items())
    res = client.get("/api/home", cookies={"ansai_id_session": "tok"})
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert len(data["agents"]) == 2
    first = data["agents"][0]
    assert first["id"] == "rec-test-1"
    assert first["kind"] == "The Bookkeeper"
    assert first["agentName"] == "bookkeeper-agent-zawadi"
    assert first["businessName"] == "Zawadi Crafts"
    assert first["state"]["label"] == "On trial"
    assert first["trialDaysLeft"] in (4, 5)  # ends ~4 days out, ceiling-counted
    assert "left of your free week" in first["state"]["detail"]
    assert first["deskUrl"] == "/lease/rec-test-1"
    assert set(first.keys()) == {
        "id", "kind", "agentName", "businessName", "state",
        "trialEndsAt", "trialDaysLeft", "createdAt", "deskUrl",
    }
    second = data["agents"][1]
    assert second["kind"] == "The Shop Agent"
    assert second["state"]["label"] == "Active"
    assert second["trialDaysLeft"] is None


def test_home_projection_drops_internal_fields(monkeypatch):
    _id_in(monkeypatch)
    _google_out(monkeypatch)
    monkeypatch.setattr(server, "_fetch_store_records", lambda cookie: _fixture_list_items())
    res = client.get("/api/home", cookies={"ansai_id_session": "tok"})
    text = res.text
    for marker in (
        "zawadi@example.com",  # customer/renter email
        "+254700000000",       # customer phone
        "777777",              # pricing internals
        "SECRET-FOUNDATION",   # foundation internals
        "op@example.com",      # accountable operator email
        "ansai-id:abc",        # renter id
        "accountable_operator",
        "renter",
        "totalKes",
    ):
        assert marker not in text, marker


def test_home_api_empty_list_is_ok(monkeypatch):
    _id_in(monkeypatch)
    _google_out(monkeypatch)
    monkeypatch.setattr(server, "_fetch_store_records", lambda cookie: [])
    res = client.get("/api/home", cookies={"ansai_id_session": "tok"})
    assert res.status_code == 200
    assert res.json() == {"ok": True, "agents": []}


def test_home_api_store_down_becomes_plain_502(monkeypatch):
    _id_in(monkeypatch)
    _google_out(monkeypatch)

    def down(cookie):
        raise server._StoreDown()

    monkeypatch.setattr(server, "_fetch_store_records", down)
    res = client.get("/api/home", cookies={"ansai_id_session": "tok"})
    assert res.status_code == 502
    body = res.json()
    assert body["ok"] is False
    assert body["error"] == "store_unreachable"
    assert body["message"]


# --- the Store list fetch itself ---------------------------------------------------


class _FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_fetch_records_forwards_cookies_and_timeout(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["cookie"] = req.headers.get("Cookie")
        seen["timeout"] = timeout
        return _FakeResponse({"records": [{"id": "rec-1", "jobId": "shop"}, "junk", 7]})

    monkeypatch.setattr(server.urllib.request, "urlopen", fake_urlopen)
    records = server._fetch_store_records("ansai_id_session=tok1; as_google=gtok")
    assert records == [{"id": "rec-1", "jobId": "shop"}]  # non-dict entries dropped
    assert seen["url"] == server.STORE_BASE + "/api/provision"
    assert seen["cookie"] == "ansai_id_session=tok1; as_google=gtok"
    assert seen["timeout"] == 4


def test_fetch_records_failures_become_store_down(monkeypatch):
    def raising(code):
        def fake_urlopen(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, code, "err", None, None)

        return fake_urlopen

    for code in (401, 500):
        monkeypatch.setattr(server.urllib.request, "urlopen", raising(code))
        try:
            server._fetch_store_records("ansai_id_session=tok")
        except server._StoreDown:
            pass
        else:
            raise AssertionError(f"Store {code} on the list should raise _StoreDown")

    monkeypatch.setattr(
        server.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse({"nope": 1})
    )
    try:
        server._fetch_store_records("ansai_id_session=tok")
    except server._StoreDown:
        pass
    else:
        raise AssertionError("a list-less payload should raise _StoreDown")


def test_cookie_header_forwards_google_cookie_too():
    class FakeRequest:
        cookies = {"ansai_id_session": "a", "as_session": "b", "as_google": "c", "theme": "dark"}

    header = server._store_cookie_header(FakeRequest())
    assert header == "ansai_id_session=a; as_session=b; as_google=c"


# --- Google admission: customer routes only ----------------------------------------


def test_google_session_admitted_to_home_page(monkeypatch):
    _id_out(monkeypatch)
    _google_in(monkeypatch)
    res = client.get("/home", cookies={"as_google": "gtok"})
    assert res.status_code == 200
    assert "Your agents" in res.text


def test_google_session_admitted_to_home_api(monkeypatch):
    _id_out(monkeypatch)
    _google_in(monkeypatch)
    monkeypatch.setattr(server, "_fetch_store_records", lambda cookie: [])
    res = client.get("/api/home", cookies={"as_google": "gtok"})
    assert res.status_code == 200
    assert res.json() == {"ok": True, "agents": []}


def test_google_session_admitted_to_lease_routes(monkeypatch):
    _id_out(monkeypatch)
    _google_in(monkeypatch)
    page = client.get("/lease/rec-1", cookies={"as_google": "gtok"})
    assert page.status_code == 200
    monkeypatch.setattr(
        server,
        "_fetch_store_record",
        lambda rid, cookie: {"id": "rec-1", "jobId": "shop", "status": "converted", "spec": {}},
    )
    res = client.get("/api/lease/rec-1", cookies={"as_google": "gtok"})
    assert res.status_code == 200
    assert res.json()["kind"] == "The Shop Agent"


def test_google_session_refused_outside_customer_routes(monkeypatch):
    _id_out(monkeypatch)
    _google_in(monkeypatch)
    for path in ("/", "/platform"):
        res = client.get(path, cookies={"as_google": "gtok"})
        assert res.status_code == 302, path
        assert res.headers["location"] == server.ID_BASE + "/home.html"
    res = client.get("/api/platform/agents", cookies={"as_google": "gtok"})
    assert res.status_code == 401
    res = client.get("/api/agents", cookies={"as_google": "gtok"})
    assert res.status_code == 401


def test_unverified_google_cookie_is_refused_everywhere(monkeypatch):
    _signed_out(monkeypatch)
    res = client.get("/home", cookies={"as_google": "forged"})
    assert res.status_code == 302
    res = client.get("/api/home", cookies={"as_google": "forged"})
    assert res.status_code == 401


def test_id_session_still_admitted_everywhere(monkeypatch):
    _id_in(monkeypatch)
    _google_out(monkeypatch)
    assert client.get("/", cookies={"ansai_id_session": "tok"}).status_code == 200
    assert client.get("/platform", cookies={"ansai_id_session": "tok"}).status_code == 200
    assert client.get("/home", cookies={"ansai_id_session": "tok"}).status_code == 200
    res = client.get("/api/platform/agents", cookies={"ansai_id_session": "tok"})
    assert res.status_code == 200


# --- the Google verification call itself --------------------------------------------


def test_google_person_verifies_against_store_session(monkeypatch):
    server._google_cache.clear()
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["cookie"] = req.headers.get("Cookie")
        seen["timeout"] = timeout
        return _FakeResponse(
            {"authed": True, "via": "google", "person": {"full_name": "G", "email": "g@x.co"}}
        )

    monkeypatch.setattr(server.urllib.request, "urlopen", fake_urlopen)
    person = server._google_person("gtok")
    assert person == {"full_name": "G", "email": "g@x.co"}
    assert seen["url"] == server.STORE_BASE + "/api/session"
    assert seen["cookie"] == "as_google=gtok"  # ONLY the Google cookie crosses
    assert seen["timeout"] == 3.5


def test_google_person_fails_closed(monkeypatch):
    server._google_cache.clear()
    for payload in (
        {"authed": False},
        {"authed": True, "via": "passcode", "person": {"full_name": "Op"}},
        {"authed": True, "via": "ansai-id", "person": {"full_name": "Id"}},
        {"gate": True},
    ):
        monkeypatch.setattr(
            server.urllib.request,
            "urlopen",
            lambda req, timeout=None, p=payload: _FakeResponse(p),
        )
        assert server._google_person("tok-" + json.dumps(payload)) is None, payload

    def boom(req, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(server.urllib.request, "urlopen", boom)
    assert server._google_person("tok-down") is None
    assert server._google_person("") is None


# --- trial time-left wording ----------------------------------------------------------


def test_home_state_trial_days_left():
    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    item = {
        "id": "rec-9",
        "jobId": "bursar",
        "status": "trial_active",
        "trialEndsAt": "2026-11-24T13:00:00+00:00",  # 3 days 1h out -> 4 ceiling days
        "agentName": "bursar-agent",
    }
    card = server._project_home_agent(item, now)
    assert card["kind"] == "The Bursar"
    assert card["state"]["label"] == "On trial"
    assert card["trialDaysLeft"] == 4
    assert card["state"]["detail"] == "4 days left of your free week"
    assert card["deskUrl"] == "/lease/rec-9"
