"""Office: the agent visualization + chat UI.

One FastAPI service (default http://localhost:8080):

  - GET  /                -> the canvas office (office/static/index.html)
  - GET  /events          -> SSE stream of agent-lifecycle events
  - POST /events/ingest  -> relay endpoint for out-of-process emitters
                            (agents/events.py POSTs here); rebroadcasts
  - GET  /api/agents     -> [{id, name, role, color, state, last_activity}]
  - POST /api/chat       -> chat with one agent, text only

Event flow:  agents -> agents/events.py -> POST /events/ingest -> SSE -> canvas.
Chat path:   browser -> POST /api/chat -> build agent -> gateway -> reply.

CHAT IS TEXT ONLY. Chat agents are built with no tools attached, so a chat
reply can never move money, send messages, or touch integrations. Anything
irreversible still goes through policy/approvals.py, which the chat path
never calls. Chat also never sees transcripts — it is a fresh conversation
each turn.

Run:  uvicorn office.server:app --host 127.0.0.1 --port 8080   (from repo root)
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "agents"))

from mini_agent import build_mini_agent  # noqa: E402
from mother_agent import build_mother_agent  # noqa: E402
import events as event_bus  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_INDEX = os.path.join(HERE, "static", "index.html")

# Roster: the Baraza as an office floor. Colors: indigo + gold are the
# company colors; the rest distinguish the desks.
AGENTS = {
    "tangaza": {
        "id": "tangaza",
        "name": "Tangaza",
        "role": "Marketing & Sales",
        "color": "#4f46e5",
    },
    "fundi": {
        "id": "fundi",
        "name": "Fundi",
        "role": "Product & Engineering",
        "color": "#0d9488",
    },
    "jabari": {
        "id": "jabari",
        "name": "Jabari",
        "role": "Chair / supervisor",
        "color": "#b45309",
    },
    "sanaa": {
        "id": "sanaa",
        "name": "Sanaa",
        "role": "Studios / creative",
        "color": "#db2777",
    },
    "akiba": {
        "id": "akiba",
        "name": "Akiba",
        "role": "Finance & Ops",
        "color": "#16a34a",
    },
    "dadisi": {
        "id": "dadisi",
        "name": "Dadisi",
        "role": "Labs scout",
        "color": "#7c3aed",
    },
}

CHAT_INSTRUCTIONS = {
    "tangaza": (
        "You are Tangaza, Marketing & Sales lead at Ansai Technologies. "
        "Answer the human's question directly and briefly, in plain text. "
        "You have no tools in this chat — describe, don't do."
    ),
    "fundi": (
        "You are Fundi, Product & Engineering lead at Ansai Technologies. "
        "Answer the human's question directly and briefly, in plain text. "
        "You have no tools in this chat — describe, don't do."
    ),
    "jabari": (
        "You are Jabari, chair of the Ansai Baraza (agent council). "
        "Answer the human's question directly and briefly, in plain text. "
        "You supervise Tangaza (sales), Fundi (engineering), Sanaa (studios), "
        "Akiba (finance), and Dadisi (labs scout). "
        "You have no tools in this chat — describe, don't do."
    ),
    "sanaa": (
        "You are Sanaa, Studios / creative lead at Ansai Technologies. "
        "Answer the human's question directly and briefly, in plain text. "
        "You have no tools in this chat — describe, don't do."
    ),
    "akiba": (
        "You are Akiba, Finance & Ops lead at Ansai Technologies. "
        "Answer the human's question directly and briefly, in plain text. "
        "You have no tools in this chat — describe, don't do."
    ),
    "dadisi": (
        "You are Dadisi, Labs scout at Ansai Technologies — you explore new "
        "ideas and report back. "
        "Answer the human's question directly and briefly, in plain text. "
        "You have no tools in this chat — describe, don't do."
    ),
}

# Live state, derived from the event stream. States: idle | working |
# thinking | error. Unknown agent ids are tracked too (spare desk).
_state: dict = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _agent_state(agent_id: str) -> dict:
    if agent_id not in _state:
        meta = AGENTS.get(agent_id, {"name": agent_id, "role": "agent", "color": "#6b7280"})
        _state[agent_id] = {
            "id": agent_id,
            "name": meta["name"],
            "role": meta["role"],
            "color": meta["color"],
            "state": "idle",
            "last_activity": "waiting",
            "last_ts": _now(),
        }
    return _state[agent_id]


# Event type -> (state, activity-prefix). The canvas maps state -> animation.
EVENT_STATES = {
    "agent_spawn": ("idle", None),
    "llm_start": ("working", None),
    "llm_end": ("idle", None),
    "tool_call": ("working", None),
    "handoff": ("thinking", None),
    "agent_idle": ("idle", None),
    "agent_error": ("error", None),
    "chat_message": ("working", None),
}


def apply_event(event: dict) -> dict:
    """Fold one event into live state; returns the normalized event."""
    etype = str(event.get("type", "unknown"))
    agent = str(event.get("agent", "unknown"))
    detail = str(event.get("detail", ""))[:140]
    st = _agent_state(agent)
    if etype in EVENT_STATES:
        new_state, _ = EVENT_STATES[etype]
        # A finished chat reply settles back to idle.
        if etype == "chat_message" and detail.startswith("out:"):
            new_state = "idle"
        st["state"] = new_state
    st["last_activity"] = detail or etype.replace("_", " ")
    st["last_ts"] = event.get("ts") or _now()
    return {"ts": st["last_ts"], "type": etype, "agent": agent, "detail": st["last_activity"]}


app = FastAPI(title="Ansai Office")

# SSE fan-out. Hand-rolled on asyncio.Queue — no extra dependency.
_subscribers: set = set()


async def _broadcast(event: dict):
    dead = []
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            dead.append(q)
    for q in dead:
        _subscribers.discard(q)


def _snapshot_event() -> dict:
    for aid in AGENTS:
        _agent_state(aid)
    return {
        "ts": _now(),
        "type": "snapshot",
        "agent": "office",
        "detail": "",
        "agents": list(_state.values()),
    }


@app.get("/")
def index():
    return FileResponse(STATIC_INDEX, media_type="text/html")


@app.get("/events")
async def events(request: Request):
    """SSE stream. First message is a snapshot so late joiners see true state."""
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.add(queue)

    async def gen():
        try:
            yield f"data: {json.dumps(_snapshot_event())}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keep proxies from closing idle streams
                    continue
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            _subscribers.discard(queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/events/ingest")
async def ingest(request: Request):
    """Accept one event from an out-of-process emitter, rebroadcast it."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid json"}, status_code=400)
    if not isinstance(body, dict) or "type" not in body or "agent" not in body:
        return JSONResponse({"ok": False, "error": "need {type, agent}"}, status_code=400)
    event = apply_event(body)
    await _broadcast(event)
    return {"ok": True}


@app.get("/api/agents")
def list_agents():
    for aid in AGENTS:
        _agent_state(aid)
    return [_state[aid] for aid in AGENTS]


class ChatIn(BaseModel):
    agent: str = Field(pattern="^(tangaza|fundi|jabari|sanaa|akiba|dadisi)$")
    message: str = Field(min_length=1, max_length=500)


def _build_chat_agent(agent_id: str):
    """Text-only agent for chat: no tools attached, ever."""
    if agent_id == "jabari":
        return build_mother_agent()
    return build_mini_agent(agent_id, CHAT_INSTRUCTIONS[agent_id], tools=[])


@app.post("/api/chat")
async def chat(body: ChatIn):
    msg = body.message.strip()
    event_bus.emit("chat_message", body.agent, f"in: {msg[:100]}")
    try:
        agent = _build_chat_agent(body.agent)
        # Direct run (not supervise/run_task): chat is a fresh turn, text only.
        response = agent.run(msg)
        reply = (response.content or "").strip()[:2000] or "(no reply)"
    except Exception as exc:
        event_bus.emit("agent_error", body.agent, f"chat failed: {type(exc).__name__}")
        return JSONResponse({"ok": False, "error": "agent failed"}, status_code=502)
    event_bus.emit("chat_message", body.agent, f"out: {reply[:100]}")
    return {"ok": True, "reply": reply}


@app.get("/api/health")
def health():
    return {"ok": True, "ts": _now(), "agents": len(_state)}
