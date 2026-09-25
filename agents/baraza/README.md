# Baraza 2.0 spike

The mother-agent pattern dogfooded on Ansai itself: **Jabari** supervises two
department minis — **Tangaza** (Marketing & Sales) and **Fundi**
(Product & Engineering) — through one weekly-cycle task, end to end, on the
substrate (gateway -> agents -> handoff summaries -> supervisor).

## Run

```bash
# from repo root, with the gateway up:
export GATEWAY_URL=http://localhost:4000
export LITELLM_MASTER_KEY=sk-ansai-dev-local   # or your group virtual keys
python agents/baraza/run_weekly_cycle.py
```

## What it does (toy task: the Monday weekly brief)

1. Tangaza (mini, `workhorse`) drafts the week's pipeline notes from toy input.
2. Fundi (mini, `workhorse`) drafts the build status from toy input.
3. Each compresses its result via `handoff.summarize_state` — Jabari never
   sees their working text.
4. Jabari (mother, `thinker`) merges the two summaries into one decision
   brief and flags anything needing the founder.

## What it proves

- The full loop runs on the gateway (model groups, failover, spend caps).
- The handoff contract holds under a real two-worker cycle.
- The supervisor's output format is stable enough to feed the blackboard later.

## What it is not (yet)

- Not connected to real data (toy inputs inline).
- No persistence of the brief (stdout only — blackboard writer is a later phase).
- No HITL wiring in the loop (policy/approvals.py is standalone until Phase 3).
