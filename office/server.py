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
  - GET  /api/blackboard -> tail of council/log.md (ansai-core, via GitHub)
  - GET  /api/approvals/pending -> HITL approval cards for gated tool calls
  - POST /api/approvals/{id}/approve|deny

Access:    every route except GET /api/health and POST /events/ingest
           requires a live Ansai ID session (the gate below the app
           definition). The tunnel may stay up because the server itself
           now checks who is asking.

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

Sentinel is the house watchman, NOT a council seat (no vote): a seventh chat
participant whose replies come from a direct Meta API call (see
_sentinel_reply) — text only, NO tools, NO Hermes session, never the
worker profile the six seats get.

Chat contract:
  POST /api/chat {targets: ["tangaza", ...], message: "..."}
    - targets: 0..7 chat-participant ids (six seats + sentinel); "everyone"
      expands to the six council seats only (Sentinel is not a seat and is
      never swept in), order preserved, deduped. No @mention in the UI ->
      targets: ["jabari"] (chair speaks).
    - Backward compat: {agent: "<id>", message} maps to {targets: ["<id>"]}.
  -> {ok: true, accepted: [...], seq: <human msg seq>} immediately.
     Replies arrive later via GET /api/chat/log?since=<seq>.

Run:  uvicorn office.server:app --host 127.0.0.1 --port 8080   (from repo root)
"""

import asyncio
import base64
import importlib.util
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
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
    # Sentinel: house watchman, NOT a council seat, no vote. Listed here so
    # it can be @mentioned in chat and seen on the floor; handled separately
    # in _run_chat_agent (direct Meta call, no tools — see _sentinel_reply).
    "sentinel": {
        "id": "sentinel",
        "name": "Sentinel",
        "role": "House watchman (not a seat)",
        "color": "#374151",
    },
}

# The six council seats (Baraza). @everyone means these six only — Sentinel
# is a chat participant, not a seat, and is never swept into @everyone.
COUNCIL_IDS = ["tangaza", "fundi", "jabari", "sanaa", "akiba", "dadisi"]

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

# Sentinel's system prompt. Kept out of WORKER_CHAT_INSTRUCTIONS on purpose:
# Sentinel must never receive the worker tool profile.
SENTINEL_INSTRUCTIONS = (
    "You are Sentinel, house watchman for Ansai Technologies "
    "(founder: Melchizedek, Nairobi). House watchman (not a seat) — not a "
    "council seat, no vote. Facts carry dates; UNSURE is a valid state; "
    "never record a proposal as delivered work. Decisions, sends, merges "
    "and money belong to Melchizedek alone. Answer directly and briefly, "
    "plain text. You have no tools in this chat — describe, don't do."
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
    with open(CHAT_LOG_PATH, encoding="utf-8", errors="replace") as f:  # legacy log has cp1252 bytes
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


def _hermes_env(key: str) -> str:
    """Env var, falling back to ~/.hermes/.env. Value is never logged."""
    val = os.environ.get(key, "")
    if val:
        return val
    env_file = os.path.expanduser("~/.hermes/.env")
    try:
        for line in open(env_file, encoding="utf-8", errors="ignore"):
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _sentinel_reply(message: str, recent: list) -> str:
    """Sentinel chat reply: direct Meta API call. Text only, NO tools,
    NO Hermes session. Recent shared-log entries become the conversation
    (founder -> user, Sentinel -> assistant, seats -> named user turns)."""
    key = _hermes_env("META_API_KEY") or _hermes_env("MODEL_API_KEY")
    if not key:
        raise RuntimeError("no META_API_KEY / MODEL_API_KEY available for Sentinel")
    msgs = [{"role": "system", "content": SENTINEL_INSTRUCTIONS}]
    for e in recent:
        author = e.get("author", "")
        text = str(e.get("text", ""))
        if author == "human":
            msgs.append({"role": "user", "content": text})
        elif author == "sentinel":
            msgs.append({"role": "assistant", "content": text})
        elif author in AGENTS:
            msgs.append({"role": "user", "content": f"{AGENTS[author]['name']}: {text}"})
        # system notes are office noise for Sentinel; skip them
    if not (msgs[-1]["role"] == "user" and msgs[-1]["content"] == message):
        msgs.append({"role": "user", "content": message})
    req = urllib.request.Request(
        "https://api.meta.ai/v1/chat/completions",
        data=json.dumps(
            {"model": "muse-wonder-1.0", "messages": msgs, "max_tokens": 800}
        ).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.load(resp)
    return (data["choices"][0]["message"]["content"] or "").strip()


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

# --- Ansai ID gate -----------------------------------------------------------
# The floor is private. Every route except /api/health and /events/ingest
# requires a live Ansai ID session: the browser carries the
# ansai_id_session cookie (Domain=.ansaitechnologies.co.ke) from signing in
# at id.ansaitechnologies.co.ke, and the gate forwards ONLY that cookie to
# the ID service's /session endpoint - the same contract as the estate's
# other Ansai ID cutovers (Board, Studio, Store). Any doubt (no cookie,
# non-200, timeout, bad JSON) fails closed: pages redirect to the Ansai ID
# sign-in, API calls get a 401. Verdicts are cached briefly (60s for a
# person, 10s for a rejection) so the floor does not hammer the ID service.
# /events/ingest stays open on purpose: out-of-process emitters on this
# machine (agents/events.py) hold no browser cookie, and ingest accepts
# display events only - it runs no tools and moves no money.
# OFFICE_ID_GATE=off disables the gate for local development only; never
# run the tunnel with it off.
ID_BASE = os.environ.get("ANSAI_ID_URL", "https://id.ansaitechnologies.co.ke")
_ID_PUBLIC_PATHS = {"/api/health", "/events/ingest"}
_id_cache: dict = {}
_id_cache_lock = threading.Lock()


def _id_person(token: str):
    """Return the Ansai ID person for a session token, or None."""
    if not token:
        return None
    now = time.time()
    with _id_cache_lock:
        hit = _id_cache.get(token)
        if hit and hit[1] > now:
            return hit[0]
    person = None
    try:
        req = urllib.request.Request(
            ID_BASE + "/session",
            headers={"Cookie": "ansai_id_session=" + token},
        )
        with urllib.request.urlopen(req, timeout=3.5) as res:
            if res.status == 200:
                data = json.loads(res.read().decode("utf-8"))
                person = data.get("person") or None
    except Exception:
        person = None
    with _id_cache_lock:
        _id_cache[token] = (person, now + (60 if person else 10))
    return person


@app.middleware("http")
async def ansai_id_gate(request, call_next):
    if os.environ.get("OFFICE_ID_GATE", "on").lower() == "off":
        return await call_next(request)
    if request.url.path in _ID_PUBLIC_PATHS:
        return await call_next(request)
    person = await asyncio.to_thread(
        _id_person, request.cookies.get("ansai_id_session", "")
    )
    if person:
        return await call_next(request)
    if request.url.path.startswith("/api/") or request.url.path == "/events":
        return JSONResponse(
            {"ok": False, "error": "ansai_id_required"}, status_code=401
        )
    return RedirectResponse(ID_BASE + "/home.html", status_code=302)


# --- end Ansai ID gate -------------------------------------------------------


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
    targets: list[str] = Field(default_factory=list, min_length=0, max_length=7)
    agent: str | None = None  # legacy single-target field; maps to targets
    message: str = Field(min_length=1, max_length=500)


def _run_chat_agent(agent_id: str, message: str) -> None:
    """One chat turn for one agent, on a daemon thread.

    Council seats get the worker tool profile (read tools free, writes/shell/
    sends gated by the approval queue) plus the last 30 shared-log entries,
    so each reads what everyone said before replying. Sentinel (house
    watchman, not a seat) is the exception: _sentinel_reply answers via a
    direct Meta API call — text only, no tools, no Hermes session. The
    reply lands in the shared log; the UI polls for it.
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
        if agent_id == "sentinel":
            # House watchman (not a seat): direct Meta call, text only.
            # Never build_mini_agent / get_tools("worker") for Sentinel.
            reply = _sentinel_reply(message, recent)[:2000] or "(no reply)"
        else:
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
        # @everyone: the six council seats only. Sentinel (house watchman,
        # not a seat) is only spoken to when @mentioned directly.
        targets = list(COUNCIL_IDS)
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
    if len(targets) > 7:
        return JSONResponse(
            {"ok": False, "error": "too many targets"},
            status_code=422,
        )

    blocked = [x for x in targets if x in _disabled]
    if blocked:
        names = ", ".join(AGENTS[x]["name"] for x in blocked)
        return JSONResponse({"ok": False, "error": f"disabled by founder: {names}"}, status_code=422)
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


# --- Council blackboard (read-only) ---
_board_cache: dict = {"ts": 0.0, "data": None}


@app.get("/api/blackboard")
def blackboard():
    """Tail of council/log.md from Ansai-technologies/ansai-core (cached 5 min).

    Sliced from the last '## Baraza daily cycle' header. Read-only: this
    endpoint never writes to GitHub. Token is never logged or returned.
    """
    if _board_cache["data"] and time.time() - _board_cache["ts"] < 300:
        return _board_cache["data"]
    # Token candidates, Hermes file first: gateway/.env's GITHUB_TOKEN is a
    # fine-grained PAT scoped to ansai-substrate and 404s on ansai-core, so
    # an env-first lookup would shadow the token that can read the board.
    candidates = []
    env_file = os.path.expanduser("~/.hermes/.env")
    try:
        for line in open(env_file, encoding="utf-8", errors="ignore"):
            if line.strip().startswith("GITHUB_TOKEN="):
                candidates.append(line.split("=", 1)[1].strip())
    except OSError:
        pass
    if os.environ.get("GITHUB_TOKEN"):
        candidates.append(os.environ["GITHUB_TOKEN"])
    candidates = [c for i, c in enumerate(candidates) if c and c not in candidates[:i]]
    if not candidates:
        return JSONResponse({"ok": False, "error": "no GITHUB_TOKEN"}, status_code=503)
    doc = None
    last_exc: Exception | None = None
    for token in candidates:
        req = urllib.request.Request(
            "https://api.github.com/repos/Ansai-technologies/ansai-core/contents/council/log.md",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "User-Agent": "ansai-office"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                doc = json.load(resp)
            break
        except Exception as exc:  # 404/401 from a repo-scoped token: try next
            last_exc = exc
    if doc is None:
        return JSONResponse({"ok": False, "error": f"blackboard fetch failed: {type(last_exc).__name__}"}, status_code=502)
    text = base64.b64decode(doc["content"]).decode("utf-8", errors="replace")
    marker = text.rfind("## Baraza daily cycle")
    tail = text[marker:] if marker >= 0 else text[-6000:]
    data = {"ok": True, "sha": doc.get("sha", "")[:10], "cycle": tail.splitlines()[0] if tail else "", "tail": tail[-6000:]}
    _board_cache.update(ts=time.time(), data=data)
    return data


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


# --- Ansai Platform (modern agent console, /platform) ---
# Model routing, as the founder sees it. Council seats talk to the LiteLLM
# gateway by GROUP (never a provider); Sentinel goes direct to Meta.
MODEL_ROUTES = {
    "jabari": {"group": "thinker", "label": "gateway · thinker"},
    "tangaza": {"group": "workhorse", "label": "gateway · workhorse"},
    "fundi": {"group": "workhorse", "label": "gateway · workhorse"},
    "sanaa": {"group": "workhorse", "label": "gateway · workhorse"},
    "akiba": {"group": "workhorse", "label": "gateway · workhorse"},
    "dadisi": {"group": "workhorse", "label": "gateway · workhorse"},
    "sentinel": {"group": "muse-wonder-1.0", "label": "Meta direct · muse-wonder-1.0 · no tools"},
}
_disabled: set = set()  # founder-managed from /platform; memory-only


@app.get("/platform")
def platform_page():
    return FileResponse(os.path.join(STATIC_DIR, "platform.html"), media_type="text/html")


@app.get("/api/platform/agents")
def platform_agents():
    out = []
    for aid, meta in AGENTS.items():
        st = _agent_state(aid)
        out.append({**st, "enabled": aid not in _disabled,
                    "seat": aid in COUNCIL_IDS,
                    "route": MODEL_ROUTES.get(aid, {"group": "?", "label": "?"})})
    return out


class EnabledIn(BaseModel):
    enabled: bool


@app.post("/api/agents/{agent_id}/enabled")
def set_enabled(agent_id: str, body: EnabledIn):
    if agent_id not in AGENTS:
        return JSONResponse({"ok": False, "error": "unknown agent"}, status_code=404)
    (_disabled.discard if body.enabled else _disabled.add)(agent_id)
    _log("system", f"{AGENTS[agent_id]['name']} {'enabled' if body.enabled else 'disabled'} by founder.")
    return {"ok": True, "agent": agent_id, "enabled": body.enabled}


class OrchestrateIn(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    participants: list[str] = Field(default_factory=list, max_length=7)


def _orchestrate(topic: str, participants: list) -> None:
    """One council session: seats speak IN ORDER, each reading the shared
    log (which by then holds the previous seats' replies), then the chair
    synthesises. This is agent-to-agent talk, not parallel replies."""
    _log("system", f"Council session convened: {topic}")
    for aid in participants:
        _run_chat_agent(aid, topic)
    if "jabari" not in participants:
        _run_chat_agent("jabari", f"Synthesise this council session on: {topic} "
                        "Give: decisions, open questions, and what is Melchizedek's hand alone.")
    _log("system", "Council session complete.")


@app.post("/api/orchestrate")
def orchestrate(body: OrchestrateIn):
    parts = [p for p in dict.fromkeys(body.participants) if p in COUNCIL_IDS and p not in _disabled]
    if not parts:
        parts = [c for c in COUNCIL_IDS if c not in _disabled]
    if not parts:
        return JSONResponse({"ok": False, "error": "all seats disabled"}, status_code=422)
    entry = _log("human", f"Convene the council: {body.topic.strip()}")
    threading.Thread(target=_orchestrate, args=(body.topic.strip(), parts), daemon=True).start()
    return {"ok": True, "accepted": parts, "seq": entry["seq"]}


# --- Agent lease desk (/lease/{record_id}) -----------------------------------
# The Agent Store's trial handoff ("Open your agent's desk") points here:
# agents.ansaitechnologies.co.ke/lease/<record-id>. The page is a customer
# surface served by this office; the record itself stays in the Store. The
# browser never talks to the Store directly — /api/lease/{id} fetches the
# record server-side, forwarding ONLY the caller's own session cookies
# (ansai_id_session, and as_session when present), and relays a SANITISED
# projection: the fields the desk displays, nothing else. Renter PII,
# answers, the audit trail, pricing internals and wallet snapshots never
# cross. The Store's read is session-scoped, so a record the caller may not
# see comes back from the Store as a 401/404 and is relayed as the same
# plain not-found either way — the desk cannot leak that a record exists.
# Both routes sit behind the Ansai ID gate above, exactly like /platform:
# signed-out pages redirect to the sign-in, signed-out API calls get a 401.
STORE_BASE = os.environ.get("AGENT_STORE_URL", "https://store.ansaitechnologies.co.ke")
_STORE_TIMEOUT = 4  # seconds; the desk must fail fast and plainly, never hang

# Store job id -> the name a customer knows it by (the Store's own job names).
JOB_KIND_NAMES = {
    "bookkeeper": "The Bookkeeper",
    "shop": "The Shop Agent",
    "bursar": "The Bursar",
    "job-hunter": "The Job Hunter",
    "outreach": "The Outreach Agent",
}

# Voice preset id -> display name, per template (the Store's job definitions
# own these words; ids repeat across templates with different names, so the
# map is keyed by job first). Unknown ids fall back to a title-cased id.
VOICE_PRESET_NAMES = {
    "bookkeeper": {"calm": "Calm & clear", "formal": "Formal & precise", "friendly": "Friendly & plain"},
    "bursar": {"gentle": "Gentle & respectful", "formal": "Formal school voice", "brief": "Short & plain"},
    "job-hunter": {"professional": "Steady & professional", "warm": "Warm & keen", "formal": "Formal & brief"},
    "outreach": {"warm": "Warm & personal", "direct": "Short & direct", "formal": "Formal & proper"},
    "shop": {"friendly": "Friendly shop voice", "neat": "Neat & orderly", "bright": "Bright & cheerful"},
}

# Evidence-pack trigger -> the plain words the desk uses for the statement.
_PACK_LABELS = {
    "trial_end": "End-of-trial statement",
    "conversion": "Statement from joining in full",
    "pause": "Statement from the pause",
    "on_request": "Statement you asked for",
}


class _StoreMiss(Exception):
    """The Store says this record is not there (or not this caller's to see)."""


class _StoreDown(Exception):
    """The Store could not be reached, or answered something unusable."""


def _store_cookie_header(request: Request) -> str:
    """Only the caller's own Store/ID session cookies cross to the Store."""
    parts = []
    for name in ("ansai_id_session", "as_session"):
        val = request.cookies.get(name, "")
        if val:
            parts.append(f"{name}={val}")
    return "; ".join(parts)


def _fetch_store_record(record_id: str, cookie_header: str) -> dict:
    """GET the lease record from the Store. Raises _StoreMiss / _StoreDown."""
    url = STORE_BASE + "/api/provision?id=" + urllib.parse.quote(record_id, safe="")
    headers = {"Accept": "application/json"}
    if cookie_header:
        headers["Cookie"] = cookie_header
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_STORE_TIMEOUT) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 401/403: the Store will not show this record to this caller —
        # relay as not-found so existence is never leaked. 404 likewise.
        if exc.code in (401, 403, 404):
            raise _StoreMiss() from exc
        raise _StoreDown() from exc
    except Exception as exc:  # timeout, DNS, bad JSON on the error path
        raise _StoreDown() from exc
    record = data.get("record") if isinstance(data, dict) else None
    if not isinstance(record, dict):
        raise _StoreDown()
    return record


def _parse_iso(val):
    if not val:
        return None
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except Exception:
        return None


def _lease_state(record: dict, now: datetime) -> dict:
    """The lease state in plain words, from the record's status + trial clock."""
    status = str(record.get("status") or "")
    trial = record.get("trial") if isinstance(record.get("trial"), dict) else {}
    if status == "trial_active":
        started = _parse_iso(trial.get("startedAt"))
        day = min(7, max(1, (now - started).days + 1)) if started else None
        return {
            "code": "trial",
            "label": "On trial",
            "detail": f"day {day} of 7" if day else "your free week is running",
        }
    if status == "provisioning":
        return {"code": "setting_up", "label": "Setting up", "detail": "we are setting up your agent now"}
    if status == "trial_expired":
        return {"code": "trial_ended", "label": "Trial ended", "detail": "your free week has ended and your agent has stopped"}
    if status == "converted":
        return {"code": "active", "label": "Active", "detail": "paid for and working at the limits you set"}
    if status == "paused":
        return {"code": "paused", "label": "Paused", "detail": "paused because a payment was missed"}
    if status == "closed":
        return {"code": "closed", "label": "Closed", "detail": "this lease has ended"}
    if status == "awaiting_payment":
        return {"code": "not_started", "label": "Not started", "detail": "waiting for its first step"}
    return {"code": "other", "label": "In progress", "detail": ""}


def _lease_voice(record: dict, job_id: str):
    """The voice profile line, when the record carries one (preset + count)."""
    voice = record.get("voice")
    if not isinstance(voice, dict):
        spec = record.get("spec") if isinstance(record.get("spec"), dict) else {}
        voice = spec.get("voice")
    if not isinstance(voice, dict) or not voice.get("preset"):
        return None
    preset = str(voice["preset"])
    name = VOICE_PRESET_NAMES.get(job_id, {}).get(preset)
    if not name:
        name = preset.replace("-", " ").replace("_", " ").title()
    samples = voice.get("samples") if isinstance(voice.get("samples"), list) else []
    return {
        "presetName": name,
        "sampleCount": len([s for s in samples if str(s).strip()]),
    }


def _lease_statements(record: dict) -> list:
    """Evidence packs, projected to what the desk shows: label, period, totals."""
    trial = record.get("trial") if isinstance(record.get("trial"), dict) else {}
    packs = trial.get("packs") if isinstance(trial.get("packs"), list) else []
    out = []
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        period = pack.get("period") if isinstance(pack.get("period"), dict) else {}
        totals = pack.get("totals") if isinstance(pack.get("totals"), dict) else {}
        sig = pack.get("signature") if isinstance(pack.get("signature"), dict) else {}
        out.append(
            {
                "label": _PACK_LABELS.get(str(pack.get("trigger") or ""), "Statement"),
                "generatedAt": pack.get("generated_at"),
                "from": period.get("from"),
                "to": period.get("to"),
                "actions": totals.get("actions"),
                "approvalsAsked": totals.get("approvalsAsked"),
                "walletMovedKes": totals.get("walletMovedKes"),
                "ref": str(sig.get("hash") or "")[:16],
            }
        )
    return out


def _project_lease(record: dict) -> dict:
    """The sanitised projection the desk renders. Nothing else crosses."""
    job_id = str(record.get("jobId") or "")
    spec = record.get("spec") if isinstance(record.get("spec"), dict) else {}
    identity = spec.get("identity") if isinstance(spec.get("identity"), dict) else {}
    policy = spec.get("policy") if isinstance(spec.get("policy"), dict) else {}
    wallet = spec.get("wallet") if isinstance(spec.get("wallet"), dict) else {}
    trial = record.get("trial") if isinstance(record.get("trial"), dict) else {}
    return {
        "ok": True,
        "id": str(record.get("id") or ""),
        "kind": JOB_KIND_NAMES.get(job_id)
        or (job_id.replace("-", " ").title() if job_id else "Your agent"),
        "agentName": str(identity.get("name") or ""),
        "purpose": str(identity.get("purpose") or ""),
        "state": _lease_state(record, datetime.now(timezone.utc)),
        "trialEndsAt": trial.get("endsAt"),
        "recordsUntil": trial.get("retentionUntil"),
        "wallet": {
            "perTxnCapKes": wallet.get("per_txn_cap"),
            "dailyCap": wallet.get("daily_cap"),
            "dailyCapUnit": wallet.get("daily_cap_unit") or "KES/day",
            "approvalThresholdKes": wallet.get("approval_threshold_kes"),
            "allowedPayees": [str(p) for p in (wallet.get("allowed_payees") or [])][:12],
        },
        "guardrails": {
            "may": [str(x) for x in (policy.get("may") or [])],
            "mustApprove": [str(x) for x in (policy.get("must_approve") or [])],
            "never": [str(x) for x in (policy.get("never") or [])],
        },
        "voice": _lease_voice(record, job_id),
        "statements": _lease_statements(record),
        "createdAt": record.get("createdAt"),
    }


@app.get("/lease/{record_id}")
def lease_page(record_id: str):
    return FileResponse(os.path.join(STATIC_DIR, "lease.html"), media_type="text/html")


@app.get("/api/lease/{record_id}")
def lease_record(record_id: str, request: Request):
    try:
        record = _fetch_store_record(record_id, _store_cookie_header(request))
    except _StoreMiss:
        return JSONResponse(
            {
                "ok": False,
                "error": "not_found",
                "message": "We couldn't find that agent — it may have been closed, or the link is incomplete.",
            },
            status_code=404,
        )
    except _StoreDown:
        return JSONResponse(
            {
                "ok": False,
                "error": "store_unreachable",
                "message": "We couldn't reach the Agent Store just now. Please try again in a moment.",
            },
            status_code=502,
        )
    return _project_lease(record)


@app.get("/api/health")
def health():
    for aid in AGENTS:
        _agent_state(aid)
    return {"ok": True, "ts": _now(), "agents": len(_state)}
