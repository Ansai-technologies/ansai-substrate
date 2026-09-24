"""Layer 2 — LLM-judge scenario runner.

Runs each scenario in evals/scenarios/ against the gateway's `judge` model group
with a fixed rubric, and writes verdicts to stdout as JSON lines.

Requires: gateway running with a `judge` group (see gateway/README.md).

Usage:
  python evals/judge.py                          # all scenarios
  python evals/judge.py evals/scenarios/sacco_balance.json
"""

import glob
import json
import os
import sys

import httpx

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
GATEWAY_API_KEY = os.environ.get(
    "GATEWAY_API_KEY",
    os.environ.get("LITELLM_MASTER_KEY", "sk-ansai-dev-local"),
)
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "judge")

RUBRIC = """You are an evaluator. Score the AGENT OUTPUT against the scenario's
expectations on a 0-2 scale per criterion (0=fail, 1=partial, 2=pass).
Output JSON only: {"scores": {"<criterion>": 0|1|2, ...}, "notes": "<one line>"}.
Criteria: {criteria}
Scenario context: {context}
AGENT OUTPUT:
{output}
"""


def judge_one(scenario: dict, agent_output: str) -> dict:
    prompt = RUBRIC.format(
        criteria=", ".join(scenario["criteria"]),
        context=scenario.get("context", ""),
        output=agent_output,
    )
    resp = httpx.post(
        f"{GATEWAY_URL}/v1/chat/completions",
        headers={"Authorization": f"Bearer {GATEWAY_API_KEY}"},
        json={
            "model": JUDGE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"] or "{}"
    try:
        verdict = json.loads(content)
    except json.JSONDecodeError:
        verdict = {"scores": {}, "notes": f"unparseable judge output: {content[:200]}"}
    return {"scenario": scenario["name"], "verdict": verdict}


def main() -> None:
    paths = sys.argv[1:] or sorted(glob.glob("evals/scenarios/*.json"))
    for path in paths:
        with open(path) as f:
            scenario = json.load(f)
        # v0: scenarios carry a canned agent_output (recorded or hand-written).
        # UPGRADE PATH: generate agent_output live by running the agent under
        # test, then judge the fresh output — the rubric path stays identical.
        result = judge_one(scenario, scenario.get("agent_output", ""))
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
