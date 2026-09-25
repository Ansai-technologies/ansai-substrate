"""Office: the agent visualization + chat UI.

One FastAPI service (default http://localhost:8080):

  - GET  /                -> the 3D diorama office (office/static/index.html)
  - GET  /static/...      -> vendored assets (portraits, three.js)
  - GET  /events          -> SSE stream of agent-lifecycle events
  - POST /events/ingest  -> relay endpoint for out-of-process emitters
                            (agents/events.py POSTs here); rebroadcasts
  - GET  /api/agents     -> [{id, name, role, color, state, last_activity}]
  - POST /api/chat       -> group chat with @mentioned agents (async accept;
                            replies + tool results stream in via the shared log)
  - GET  /api/chat/log   -> shared chat log entries (polling; ?since=<seq>)
  - GET  /api/approvals/pending -> HITL approval cards for gated tool calls
  - POST /api/approvals/{id}/approve|deny

Event flow:  agents -> agents/events.py -> POST /events/ingest -> SSE -> 3D scene.
Chat path:   browser -> POST /api/chat {targets, message} -> 202-style accept
             -> one daemon thread per target runs _run_chat_agent ->
             worker-profile agent (read tools free, writes gated by approvals)
             -> reply appended to the shared chat log -> UI polls /api/chat/log.

CHAT EXECUTES. Chat agents are built with the `worker` tool profile from
agents/tools_registry.py, so they can read, check, and look things up, and —
with human approval — write, delete, run shell commands, and send. Gated
tools block on policy/approvals.request_approval(), which appends a PENDING
record to policy/queue.jsonl; the chat UI surfaces it as an approval card and
the founder approves/denies from there. Read-only tools never block.

Shared context: every human message, agent reply, and system note lands in the
append-only office/chat-log.jsonl (loaded at startup, 300 entries in memory).
Each chat turn gets the last 30 log entries as "recent office chat", so every
agent reads what everyone said before it. The founder sees the same log the
agents see.

Chat contract:
  POST /api/chat {targets: ["tangaza", ...], message: "..."}
    - targets: 0..6 roster ids; "everyone" expands to all six, order preserved,
      deduped. No @mention in the UI -> targets: ["jabari"] (chair speaks).
    - Backward compat: {agent: "<id>", message} maps to {targets: ["<id>"]}.
  -> {ok: true, accepted: [...], seq: <human msg seq>} immediately.
     Replies arrive later via GET /api/chat/log?since=<seq>.

Run:  uvicorn office.server:app --host 127.0.0.1 --port 8080   (from repo root)
"""

import asyncio
import importlib.util
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "agents"))

# Chat approvals get a shorter fuse than background tasks (10 min): the human
# is sitting in the chat watching. Must be set BEFORE tools_registry loads the
# MCP servers, which bind policy/approvals.DEFAULT_TIMEOUT at import time.
os.environ.setdefault("APPROVAL_TIMEOUT", "600")

from mini_agent import build_mini_agent  # noqa: E402
from tools_registry import get_tools  # noqa: E402
import events as event_bus  # noqa: E402


def _load_by_path(name: str, *parts: str):
    """Load a module by file path — avoids sys.path shadowing clashes."""
    path = os.path.join(ROOT, *parts)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_approvals = _load_by_path("office_policy_approvals", "policy", "approvals.py")

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, "static")
STATIC_INDEX = os.path.join(STATIC_DIR, "index.html")

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

# Shared rules for every chat turn: read the room first, answer directly when
# it's just talk, use tools when asked to do something, and never claim an
# unapproved write as done.
_CHAT_RULES = (
    "You are in the Baraza office group chat with Melchizedek (the founder) "
    "and the other agents. The recent conversation is shown above — read it "
    "before replying, including what other agents said. "
    "If Melchizedek is just chatting or asking something you can answer directly, "
    "reply briefly in plain text (no JSON, no markdown headers). "
    "If he asks you to do, check, find, or change something, use your tools, "
    "then report what you did in one or two sentences. "
    "Read-only tools run freely. Writes, deletes, shell commands, and sends pop "
    "an approval card in the chat — briefly say what you want to do and wait for "
    "his decision; never claim you did something you didn't."
)

WORKER_CHAT_INSTRUCTIONS = {
    "tangaza": (
        "You are Tangaza, Marketing & Sales lead at Ansai Technologies. " + _CHAT_RULES
    ),
    "fundi": (
        "You are Fundi, Product & Engineering lead at Ansai Technologies. " + _CHAT_RULES
    ),
    "jabari": (
        "You are Jabari, chair of the Ansai Baraza (agent council). "
        "You supervise Tangaza (sales), Fundi (engineering), Sanaa (studios), "
        "Akiba (finance), and Dadisi (labs scout). " + _CHAT_RULES
    ),
    "sanaa": (
        "You are Sanaa, Studios / creative lead at Ansai Technologies. " + _CHAT_RULES
    ),
    "akiba": (
        "You are Akiba, Finance & Ops lead at Ansai Technologies. " + _CHAT_RULES
    ),
    "dadisi": (
        "You are Dadisi, Labs scout at Ansai Technologies — you explore new "
        "ideas and report back. " + _CHAT_RULES
    ),
}

# Shared chat log: every human message, agent reply, and system note.
# Append-only on disk (office/chat-log.jsonl); last 300 kept in memory.
# Author is "human", an agent id, or "system".
CHAT_LOG_PATH = os.path.join(HERE, "chat-log.jsonl")
CHAT_LOG: list[dict] = []
_chat_seq = 0
_chat_lock = threading.Lock()


def _log(author: str, text: str) -> dict:
    """Append one entry to the shared chat log; returns the entry."""
    global _chat_seq
    with _chat_lock:
        _chat_seq += 1
        entry = {"seq": _chat_seq, "ts": _now(), "author": author, "text": text}
        CHAT_LOG.append(entry)
        if len(CHAT_LOG) > 300:
            del CHAT_LOG[: len(CHAT_LOG) - 300]
        try:
            with open(CHAT_LOG_PATH, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # disk hiccup must never break chat
        return entry


def _load_chat_log() -> None:
    """Restore the shared log from disk at startup (keeps last 300)."""
    global _chat_seq
    if not os.path.exists(CHAT_LOG_PATH):
        return
    with open(CHAT_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if not isinstance(entry, dict) or "seq" not in entry:
                continue
            CHAT_LOG.append(entry)
            _chat_seq = max(_chat_seq, int(entry["seq"]))
    if len(CHAT_LOG) > 300:
        del CHAT_LOG[: len(CHAT_LOG) - 300]


_load_chat_log()

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


# Event type -> (state, activity-prefix). The 3D scene maps state -> animation.
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

# Vendored assets: portraits + three.js. index.html loads everything
# relative, so the office works the moment start.sh runs, even offline.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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
    targets: list[str] = Field(default_factory=list, min_length=0, max_length=6)
    agent: str | None = None  # legacy single-target field; maps to targets
    message: str = Field(min_length=1, max_length=500)


def _run_chat_agent(agent_id: str, message: str) -> None:
    """One chat turn for one agent, on a daemon thread.

    The agent gets the worker tool profile (read tools free, writes/shell/
    sends gated by the approval queue) plus the last 30 shared-log entries,
    so it reads what everyone said before replying. The reply lands in the
    shared log; the UI polls for it.
    """
    name = AGENTS[agent_id]["name"]
    prev_name = os.environ.get("AGENT_NAME")
    # Best-effort tool_call attribution (mcp servers read AGENT_NAME);
    # two threads racing here is cosmetic only.
    os.environ["AGENT_NAME"] = agent_id
    try:
        event_bus.emit("llm_start", agent_id, "working on chat task")
        with _chat_lock:
            recent = list(CHAT_LOG[-30:])
        lines = []
        for e in recent:
            author = e.get("author", "")
            if author == "human":
                who = "Melchizedek (founder)"
            elif author in AGENTS:
                who = AGENTS[author]["name"]
            else:
                who = str(author)  # system and anything else, labeled as-is
            lines.append(f"{who}: {e.get('text', '')}")
        history = "\n".join(lines) or "(no prior messages)"
        prompt = (
            "Recent office chat (you can see what everyone said):\n"
            + history
            + f"\n\nMelchizedek just wrote: {message}\nReply as {name}."
        )
        agent = build_mini_agent(
            agent_id, WORKER_CHAT_INSTRUCTIONS[agent_id], tools=get_tools("worker")
        )
        response = agent.run(prompt)
        reply = (response.content or "").strip()[:2000] or "(no reply)"
        _log(agent_id, reply)
        event_bus.emit("chat_message", agent_id, f"out: {reply[:100]}")
    except Exception as exc:
        event_bus.emit("agent_error", agent_id, f"chat failed: {type(exc).__name__}")
        _log("system", f"⚠ {name} hit an error: {type(exc).__name__}: {str(exc)[:120]}")
    finally:
        if prev_name is None:
            os.environ.pop("AGENT_NAME", None)
        else:
            os.environ["AGENT_NAME"] = prev_name


@app.post("/api/chat")
async def chat(body: ChatIn):
    targets = list(body.targets)
    if not targets and body.agent:
        targets = [body.agent]
    if not targets:
        targets = ["jabari"]  # no @mention: the chair speaks for the room
    if any(str(t).lower() == "everyone" for t in targets):
        targets = list(AGENTS.keys())  # @everyone: the whole Baraza
    # Dedupe, keep order.
    seen = set()
    deduped = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    targets = deduped
    unknown = [t for t in targets if t not in AGENTS]
    if unknown:
        return JSONResponse(
            {"ok": False, "error": f"unknown agent(s): {', '.join(unknown)}"},
            status_code=422,
        )
    if len(targets) > 6:
        return JSONResponse(
            {"ok": False, "error": "too many targets"},
            status_code=422,
        )

    msg = body.message.strip()
    entry = _log("human", msg)
    # Async accept: one daemon thread per target; replies stream into the
    # shared log and the UI polls for them. The human never waits on a model.
    for agent_id in targets:
        threading.Thread(
            target=_run_chat_agent, args=(agent_id, msg), daemon=True
        ).start()
    return {"ok": True, "accepted": targets, "seq": entry["seq"]}


@app.get("/api/chat/log")
def chat_log(since: int = 0):
    """Poll new shared-log entries: ?since=<seq> -> entries with seq > since."""
    with _chat_lock:
        entries = [e for e in CHAT_LOG if e.get("seq", 0) > since]
    return {"entries": entries}


@app.get("/api/approvals/pending")
def approvals_pending():
    """Approval cards for gated tool calls: what each agent wants to do."""
    return {"pending": _approvals.list_pending()}


@app.post("/api/approvals/{approval_id}/approve")
def approvals_approve(approval_id: str):
    if _approvals.approve(approval_id):
        return {"ok": True}
    return JSONResponse({"ok": False, "error": "no such approval"}, status_code=404)


@app.post("/api/approvals/{approval_id}/deny")
def approvals_deny(approval_id: str):
    if _approvals.deny(approval_id):
        return {"ok": True}
    return JSONResponse({"ok": False, "error": "no such approval"}, status_code=404)


@app.get("/api/health")
def health():
    return {"ok": True, "ts": _now(), "agents": len(_state)}
