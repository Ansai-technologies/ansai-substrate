"""Event bus: agent lifecycle -> office visualization (and any subscriber).

Agent code calls emit(). It is ALWAYS best-effort and non-blocking:
subscriber exceptions are swallowed, and the HTTP relay to the office
server runs on a daemon thread, so a down or slow office server can never
stall or crash an agent loop.

Event shape (small JSON — no secrets, no full prompts):
    {"ts": "<iso>", "type": "<event_type>", "agent": "<id>", "detail": "<=140 chars"}

Privacy rule: `detail` is a short human-readable summary. Never put prompts,
transcripts, tool arguments, or keys in here — the office canvas renders
these strings in speech bubbles.

Event types: agent_spawn, llm_start, llm_end, tool_call, handoff,
agent_idle, agent_error, chat_message.
"""

import json
import os
import threading
import urllib.request
from datetime import datetime, timezone

# Where the office server listens. Exported by start.sh; the default matches
# office/server.py. When nothing listens here, the relay fails silently.
OFFICE_URL = os.environ.get("OFFICE_URL", "http://localhost:8080")
RELAY_PATH = "/events/ingest"
MAX_DETAIL = 140

_subscribers: list = []


def subscribe(fn):
    """Register an in-process listener: fn(event_dict). Exceptions swallowed."""
    _subscribers.append(fn)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def emit(event_type: str, agent: str, detail: str | None = None) -> dict:
    """Publish one lifecycle event. Never raises."""
    event = {
        "ts": _now(),
        "type": event_type,
        "agent": agent,
        "detail": (detail or "")[:MAX_DETAIL],
    }
    for fn in list(_subscribers):
        try:
            fn(event)
        except Exception:
            pass

    def _relay():
        try:
            req = urllib.request.Request(
                OFFICE_URL.rstrip("/") + RELAY_PATH,
                data=json.dumps(event).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                resp.read(1)
        except Exception:
            pass  # office down or unreachable: agent work continues regardless

    threading.Thread(target=_relay, daemon=True).start()
    return event
