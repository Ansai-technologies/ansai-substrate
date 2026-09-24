"""Handoff contract: mini agent -> mother agent.

The mother agent NEVER receives raw transcripts. A mini agent compresses its
working state into a structured summary dict, and only the summary crosses the
boundary. This is the cost control that makes the supervisor pattern viable:
full transcripts through an orchestrator are what drive the 15x token blowup
flagged in the research.

Contract:
    summarize_state(transcript) -> {
        "goal": str,            # what the mini was trying to do
        "facts": [str],         # established facts, newest last
        "open_questions": [str],
        "proposed_next": str,   # what the mini recommends
    }

Size enforcement: input transcript truncated to TRANSCRIPT_BUDGET chars
(newest kept); output capped at SUMMARY_BUDGET chars of JSON.
"""

import json

TRANSCRIPT_BUDGET = 6000   # chars of transcript considered; newest kept
SUMMARY_BUDGET = 1500      # chars of summary JSON emitted
MAX_FACTS = 8
MAX_QUESTIONS = 5


def _truncate_transcript(transcript: str) -> str:
    """Keep the newest content; the end of a transcript carries the outcome."""
    if len(transcript) <= TRANSCRIPT_BUDGET:
        return transcript
    return transcript[-TRANSCRIPT_BUDGET:]


def summarize_state(transcript: str, goal: str = "") -> dict:
    """Deterministic v0 summarizer: extractive, no model call.

    Keeps this module dependency-free so the contract is testable without a
    running gateway. UPGRADE PATH: replace the body with a call to the
    gateway's `judge` group using a summarization rubric once evals show the
    heuristic losing material facts — the contract (keys + budgets) stays.
    """
    text = _truncate_transcript(transcript or "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Heuristic: assistant/model lines ending in sentence-like statements are
    # candidate facts; lines ending with "?" are candidate open questions.
    facts, questions = [], []
    for ln in lines:
        clean = ln.split(":", 1)[-1].strip() if ":" in ln[:40] else ln
        if clean.endswith("?"):
            questions.append(clean)
        elif len(clean) > 20:
            facts.append(clean)

    summary = {
        "goal": (goal or "unspecified")[:200],
        "facts": facts[-MAX_FACTS:],
        "open_questions": questions[-MAX_QUESTIONS:],
        "proposed_next": (facts[-1] if facts else "awaiting supervisor direction")[:300],
    }

    blob = json.dumps(summary, ensure_ascii=False)
    if len(blob) > SUMMARY_BUDGET:
        # Hard cap: shrink facts list until we fit; structure is never broken.
        while len(blob) > SUMMARY_BUDGET and len(summary["facts"]) > 1:
            summary["facts"] = summary["facts"][1:]
            blob = json.dumps(summary, ensure_ascii=False)
        if len(blob) > SUMMARY_BUDGET:
            summary["facts"] = summary["facts"][:1]
            summary["open_questions"] = []
            blob = json.dumps(summary, ensure_ascii=False)[:SUMMARY_BUDGET]
            summary = json.loads(blob)
    return summary


def validate_summary(summary: dict) -> bool:
    """True iff the dict honours the contract keys and size budget."""
    if not isinstance(summary, dict):
        return False
    if set(summary.keys()) != {"goal", "facts", "open_questions", "proposed_next"}:
        return False
    if not isinstance(summary["facts"], list) or not isinstance(summary["open_questions"], list):
        return False
    return len(json.dumps(summary, ensure_ascii=False)) <= SUMMARY_BUDGET
