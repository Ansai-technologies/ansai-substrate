"""M-Pesa (Daraja) MCP server — LIVE on sandbox when keys are present.

Contract (stable, pinned by evals/test_tools.py):
  get_balance(account) -> dict
  stk_push(phone, amount_kes, reference) -> dict

Behavior:
  - No DARAJA_CONSUMER_KEY/SECRET in env: both tools return the original
    stub payloads (status "stub"). Nothing touches the network. The evals
    rely on this, so keep it.
  - Keys present: real Daraja SANDBOX calls. There is deliberately NO
    production switch in v1 — the base URL is a constant below. Production
    (go-live) is a separate, reviewed change.
  - stk_push moves money: it ALWAYS goes through policy.request_approval()
    first. Denied/timeout -> {"status": "denied"} and no HTTP is attempted.

Env (all from the Daraja portal app; never commit these):
  DARAJA_CONSUMER_KEY / DARAJA_CONSUMER_SECRET   OAuth pair
  DARAJA_PASSKEY        STK password component (portal: app Test Credentials)
  DARAJA_SHORTCODE      default 174379 (sandbox test shortcode)
  DARAJA_CALLBACK_URL   where Safaricom POSTs the async result; must be a
                        public HTTPS URL for real callbacks (ngrok is fine)

Run:  python mcp/mpesa/server.py   (stdio transport, for MCP clients)
Test: pytest evals/test_tools.py   (imports the plain functions below)
"""

import base64
import os
import sys
import time

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
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - plain functions are the contract
    FastMCP = None  # type: ignore

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore


# ---------------------------------------------------------------------------
# Daraja sandbox endpoints. Constant on purpose: v1 cannot talk to production.
# ---------------------------------------------------------------------------
SANDBOX_BASE = "https://sandbox.safaricom.co.ke"
TOKEN_URL = SANDBOX_BASE + "/oauth/v1/generate?grant_type=client_credentials"
STK_PUSH_URL = SANDBOX_BASE + "/mpesa/stkpush/v1/processrequest"

_token_cache = {"token": None, "expires_at": 0.0}


def _credentials_present() -> bool:
    return bool(
        os.environ.get("DARAJA_CONSUMER_KEY")
        and os.environ.get("DARAJA_CONSUMER_SECRET")
    )


def _basic_auth() -> str:
    key = os.environ["DARAJA_CONSUMER_KEY"]
    secret = os.environ["DARAJA_CONSUMER_SECRET"]
    return base64.b64encode(f"{key}:{secret}".encode()).decode()


def _get_token() -> str:
    """OAuth token, cached in memory (Daraja tokens live ~3600s)."""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    if httpx is None:
        raise RuntimeError("httpx is not installed")
    r = httpx.get(
        TOKEN_URL,
        headers={"Authorization": f"Basic {_basic_auth()}"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + int(data.get("expires_in", 3599))
    return _token_cache["token"]


def _post_json(url: str, body: dict, token: str) -> dict:
    r = httpx.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def normalize_phone(phone: str) -> str:
    """07../2547../+2547.. -> 2547... Raises ValueError on anything else."""
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("0"):
        digits = "254" + digits[1:]
    if not (digits.startswith("254") and len(digits) == 12):
        raise ValueError(f"not a Kenyan MSISDN: {phone!r}")
    return digits


def stk_password(shortcode: str, passkey: str, timestamp: str) -> str:
    """Daraja STK password = base64(shortcode + passkey + timestamp)."""
    return base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def get_balance(account: str) -> dict:
    """Query M-Pesa account balance.

    v1: stub unless keys are set; with keys but without the Phase 0b
    credential it says so plainly instead of faking a number.
    """
    if not _credentials_present():
        return {
            "status": "stub",
            "account": account,
            "balance": None,
            "note": "no real query performed — set DARAJA_CONSUMER_KEY/SECRET to go live on sandbox",
        }
    return {
        "status": "error",
        "account": account,
        "error": (
            "balance query not wired yet (Phase 0b): needs "
            "DARAJA_SECURITY_CREDENTIAL (RSA-encrypted initiator password) plus "
            "public ResultURL/QueueTimeOutURL — see mcp/mpesa/README.md"
        ),
    }


def stk_push(phone: str, amount_kes: int, reference: str) -> dict:
    """Initiate an M-Pesa STK push (sandbox when keys are set).

    HITL is mandatory: a human approves every push via
    policy/request_approval before anything is sent. Denied (or timed
    out) approvals return {"status": "denied"} and no HTTP is attempted.
    """
    if not _credentials_present():
        return {
            "status": "stub",
            "phone": phone,
            "amount_kes": amount_kes,
            "reference": reference,
            "note": "no real push performed — set DARAJA_CONSUMER_KEY/SECRET to go live on sandbox",
        }
    try:
        msisdn = normalize_phone(phone)
    except ValueError as e:
        return {"status": "error", "error": str(e)}
    if not isinstance(amount_kes, int) or amount_kes <= 0:
        return {"status": "error", "error": "amount_kes must be a positive integer"}
    shortcode = os.environ.get("DARAJA_SHORTCODE", "174379")
    passkey = os.environ.get("DARAJA_PASSKEY", "")
    if not passkey:
        return {
            "status": "error",
            "error": "DARAJA_PASSKEY is not set (Daraja portal: your app's Test Credentials page)",
        }

    ok = request_approval(
        {
            "kind": "money",
            "summary": f"M-Pesa STK push: KSh {amount_kes} to {msisdn} (ref: {reference})",
            "payload": {
                "tool": "stk_push",
                "phone": msisdn,
                "amount_kes": amount_kes,
                "reference": reference,
            },
        }
    )
    if not ok:
        return {
            "status": "denied",
            "phone": msisdn,
            "amount_kes": amount_kes,
            "reference": reference,
        }

    timestamp = time.strftime("%Y%m%d%H%M%S")
    body = {
        "BusinessShortCode": shortcode,
        "Password": stk_password(shortcode, passkey, timestamp),
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount_kes,
        "PartyA": msisdn,
        "PartyB": shortcode,
        "PhoneNumber": msisdn,
        "CallBackURL": os.environ.get(
            "DARAJA_CALLBACK_URL", "https://example.com/daraja/callback"
        ),
        "AccountReference": reference[:12],
        "TransactionDesc": f"Ansai Tuma: {reference}"[:64],
    }
    try:
        data = _post_json(STK_PUSH_URL, body, _get_token())
    except Exception as e:  # network, auth, bad JSON — report, don't raise
        return {"status": "error", "error": f"daraja request failed: {e}"}
    if data.get("ResponseCode") == "0":
        return {
            "status": "ok",
            "checkout_request_id": data.get("CheckoutRequestID"),
            "customer_message": data.get("CustomerMessage"),
            "phone": msisdn,
            "amount_kes": amount_kes,
            "reference": reference,
            "note": (
                "sandbox: STK push accepted; test numbers auto-complete, "
                "final result arrives on DARAJA_CALLBACK_URL"
            ),
        }
    return {
        "status": "error",
        "error": data.get("ResponseDescription") or "daraja rejected the request",
        "phone": msisdn,
        "amount_kes": amount_kes,
        "reference": reference,
    }


_TOOLS = [get_balance, stk_push]

if FastMCP is not None:
    mcp = FastMCP("mpesa")
    for _fn in _TOOLS:
        mcp.tool()(_fn)


if __name__ == "__main__":
    if FastMCP is None:
        raise SystemExit("mcp package not installed; plain functions still importable for tests")
    mcp.run()
