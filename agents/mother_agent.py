"""Mother agent: the supervisor.

Receives ONLY structured summaries (see handoff.py) from mini agents — never
transcripts. It holds the full picture as merged state, resolves conflicts,
and issues directives back down.

Design rule (from the research): the supervisor reasons over summaries, and
summaries alone. If a decision needs detail the summary lacks, it asks the mini
a targeted follow-up question rather than pulling the transcript.

Requires: gateway running (see gateway/README.md). Default model group
`thinker` (DeepSeek reasoner); override with MOTHER_MODEL.
"""

import json
import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from handoff import validate_summary

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
GATEWAY_API_KEY = os.environ.get(
    "GATEWAY_API_KEY",
    os.environ.get("LITELLM_MASTER_KEY", "sk-ansai-dev-local"),
)
MODEL_GROUP = os.environ.get("MOTHER_MODEL", "thinker")

SUPERVISOR_INSTRUCTIONS = """You are a supervisor over worker agents.
You receive structured state summaries, never transcripts. For each cycle:
1. Merge the summaries into one picture: agreed facts, conflicts, open questions.
2. Resolve conflicts by asking at most one targeted follow-up per worker.
3. Emit a directive per worker: {worker, directive, rationale}.
4. Flag anything needing human approval (money, sends, deletes) — do not decide those yourself.
Output JSON only: {"merged_state": {...}, "directives": [...], "needs_human": [...]}.
"""


def build_mother_agent() -> Agent:
    return Agent(
        name="mother",
        model=OpenAIChat(
            id=MODEL_GROUP,
            base_url=f"{GATEWAY_URL}/v1",
            api_key=GATEWAY_API_KEY,
        ),
        instructions=SUPERVISOR_INSTRUCTIONS,
        markdown=False,
    )


def supervise(mother: Agent, summaries: list[dict]) -> dict:
    """One supervision cycle over validated handoff summaries."""
    for s in summaries:
        if not validate_summary(s):
            raise ValueError(f"handoff contract violated: {s}")
    prompt = (
        "Worker summaries:\n"
        + json.dumps(summaries, ensure_ascii=False, indent=2)
        + "\nProduce the supervision output."
    )
    response = mother.run(prompt)
    content = response.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Never let a malformed model reply crash the loop; surface it.
        return {"merged_state": {}, "directives": [], "needs_human": [content[:500]]}
