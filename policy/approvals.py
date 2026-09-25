"""HITL approval policy.

Any agent action that is IRREVERSIBLE goes through here and BLOCKS until a
human approves or denies it:

  - money movement (stk_push, transfers, refunds)
  - outbound sends (WhatsApp, email, SMS)
  - deletes / destructive writes

Mechanism: JSONL queue. request_approval() appends a PENDING record and polls
until a human flips it via the bundled CLI (policy/approve.py) or the record
times out (default 1h -> treated as denied). The queue file is runtime state —
gitignored, never committed.

This is policy, not a suggestion: the MCP server docstrings and the SKILL.md
guardrails both point here. An agent that bypasses this is misconfigured.
"""

import json
import os
import time
import uuid

QUEUE_PATH = os.environ.get(
    "APPROVAL_QUEUE",
    os.path.join(os.path.dirname(__file__), "queue.jsonl"),
)
POLL_INTERVAL = 2.0
DEFAULT_TIMEOUT = float(os.environ.get("APPROVAL_TIMEOUT", "3600"))  # env override; then denied


def _read_all() -> list[dict]:
    if not os.path.exists(QUEUE_PATH):
        return []
    records = []
    with open(QUEUE_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _write_all(records: list[dict]) -> None:
    tmp = QUEUE_PATH + ".tmp"
    with open(tmp, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, QUEUE_PATH)


def _set_status(approval_id: str, status: str, reason: str = "") -> bool:
    records = _read_all()
    for r in records:
        if r["id"] == approval_id:
            r["status"] = status
            r["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            r["reason"] = reason
            _write_all(records)
            return True
    return False


def approve(approval_id: str, reason: str = "") -> bool:
    """Human approves (via CLI)."""
    return _set_status(approval_id, "approved", reason)


def deny(approval_id: str, reason: str = "") -> bool:
    """Human denies (via CLI)."""
    return _set_status(approval_id, "denied", reason)


def list_pending() -> list[dict]:
    return [r for r in _read_all() if r["status"] == "pending"]


def request_approval(action: dict, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Block until a human approves/denies. Returns True iff approved.

    action: {"kind": "send"|"money"|"delete"|..., "summary": str, "payload": {...}}
    """
    record = {
        "id": uuid.uuid4().hex[:12],
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "status": "pending",
        "action": action,
        "reason": "",
    }
    records = _read_all()
    records.append(record)
    _write_all(records)

    print(f"[HITL] approval requested: {record['id']} — {action.get('summary')}")
    print(f"[HITL] decide with: python policy/approve.py approve|deny {record['id']}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        for r in _read_all():
            if r["id"] == record["id"]:
                if r["status"] == "approved":
                    print(f"[HITL] approved: {record['id']}")
                    return True
                if r["status"] == "denied":
                    print(f"[HITL] denied: {record['id']}")
                    return False
    print(f"[HITL] timed out (treated as denied): {record['id']}")
    _set_status(record["id"], "denied", "timeout")
    return False
