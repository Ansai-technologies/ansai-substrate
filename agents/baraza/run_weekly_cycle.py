"""Baraza 2.0 spike: Kiongozi supervises Tangaza + Mhandisi Mkuu.

Toy weekly-cycle task. Each mini works from toy input, hands a structured
summary up; Kiongozi merges into a decision brief. Run from repo root with the
gateway up (see agents/baraza/README.md).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mini_agent import build_mini_agent, run_task
from mother_agent import build_mother_agent, supervise
from handoff import summarize_state

# Toy inputs stand in for real department state until Phase 5 wires real data.
TANGAZA_INPUT = """Pipeline notes (toy): 21 pitches sent, 0 human replies, 2 auto-acks.
Follow-up touches not yet written. Wincost proposal still under consideration."""

MHANDISI_INPUT = """Build status (toy): gateway scaffold complete, MCP servers stubbed,
evals skeleton in place. Looply deploy still red — diagnosis awaiting founder."""


def main() -> None:
    tangaza = build_mini_agent(
        name="tangaza",
        instructions=(
            "You are Tangaza, Marketing & Sales lead. Draft concise pipeline notes "
            "from the input: what moved, what is stuck, what needs a decision. "
            "Plain text, no fluff."
        ),
    )
    mhandisi = build_mini_agent(
        name="mhandisi-mkuu",
        instructions=(
            "You are Mhandisi Mkuu, Product & Engineering lead. Draft a concise "
            "build status from the input: what shipped, what is blocked, what "
            "needs the founder. Plain text, no fluff."
        ),
    )

    tangaza_out = run_task(tangaza, TANGAZA_INPUT)
    mhandisi_out = run_task(mhandisi, MHANDISI_INPUT)

    summaries = [
        {"worker": "tangaza", **summarize_state(tangaza_out, goal="weekly pipeline notes")},
        {"worker": "mhandisi-mkuu", **summarize_state(mhandisi_out, goal="weekly build status")},
    ]

    mother = build_mother_agent()
    brief = supervise(mother, [s for s in summaries])

    print("=== BARAZA WEEKLY BRIEF (spike) ===")
    import json

    print(json.dumps(brief, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
