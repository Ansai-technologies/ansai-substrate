# Roadmap — substrate to SACCO pilot

Each phase has a **done-when** criterion. Do not start the next phase until the
current one's criterion holds — that discipline is the whole point.

## Phase 0 — Verify keys (day 0)

- Confirm DeepSeek + Gemini keys live via the gateway smoke test
  (`gateway/README.md`). Record the DeepSeek balance.
- **Done-when:** `curl` to model group `workhorse` returns 200.

## Phase 1 — Gateway (days 1–3)

- `docker compose up`, run the failover test (bogus DeepSeek key -> Gemini
  takes over), create per-group virtual keys with the COSTS.md budgets, set
  50%/80% alerts.
- **Done-when:** failover test passes and each group key has a budget + alert.

## Phase 2 — Agent skeleton (weeks 1–2)

- `pip install -r requirements.txt`; `pytest evals/test_tools.py` green.
- Run the Baraza 2.0 spike end to end; inspect Kiongozi's brief for handoff
  contract violations.
- **Done-when:** spike runs, all handoffs validate, brief is coherent.

## Phase 3 — MCP + HITL (weeks 2–3)

- Approval queue exercised end to end: `request_approval()` blocks, CLI
  approve/deny flips it, timeout denies.
- Write the first real skill consumer: a mini agent that loads
  `skills/sacco-member-onboarding/SKILL.md` and runs it against the WhatsApp
  stub, with every send gated by HITL.
- **Done-when:** full onboarding flow completes against stubs with an approval
  record per send.

## Phase 4 — Evals (weeks 3–4)

- `python evals/judge.py` runs all scenarios green; add scenarios for every
  new skill step.
- Wire `sample_prod.py` to the gateway log DB (Postgres — local compose
  service or Supabase).
- Set the quality bar: no agent ships a new capability with <2/2 on its
  scenario criteria.
- **Done-when:** judge suite green, prod sampler wired, bar documented.

## Phase 5 — Baraza 2.0, for real (weeks 4–6)

- Replace toy inputs with real department state; persist Kiongozi's brief
  (blackboard writer — new work, not in this scaffold).
- Baraza runs the Monday cycle on the substrate weekly.
- **Done-when:** two consecutive weekly briefs produced without manual repair.

## Phase 6 — SACCO WhatsApp pilot (weeks 6–12)

- Wire WhatsApp Business Cloud API (sandbox -> production), then Daraja
  sandbox for M-Pesa; every send and every stk_push behind HITL.
- 3–5 paid pilots. The pilot contract is the product spec.
- **Done-when:** one SACCO runs member onboarding + balance inquiries live
  for 2 weeks with zero unapproved sends and eval scores holding.

## Deferred, deliberately

- Training our own models.
- Temporal / durable execution — only when long runs actually break.
- x402 agent micropayments (hype-flagged; negligible real volume).
- Pay-per-crawl revenue dependence (still closed beta).
- Self-hosted Postgres for logs — only if Supabase is ever unsuitable.
- Multi-region / self-hosted models — only when a client contract demands it.
