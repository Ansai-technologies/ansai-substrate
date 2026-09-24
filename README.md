# ansai-substrate

The shared agent substrate for Ansai Technologies — **one substrate, two surfaces**.

Everything agentic the company builds (internal Baraza agents, client WhatsApp
runtimes, the mother-agent pattern) runs on this foundation: one model gateway,
one orchestration pattern, one tool layer, one approval policy, one eval harness.

```
                    +------------------+
                    |  mini agents     |  per-person / per-role workers (Agno)
                    |  mother agent    |  supervisor over structured summaries
                    +--------+---------+
                             |  OpenAI-compatible /v1  (model *groups*, never providers)
                    +--------v---------+
                    |  LiteLLM gateway |  workhorse/thinker -> DeepSeek
                    |                  |  vision/vision-cheap -> Gemini (fallback)
                    |                  |  spend caps + failover, request logging
                    +--------+---------+
                             |
            +----------------+----------------+
            | MCP tool servers                |  whatsapp (stub), mpesa (stub)
            +----------------+----------------+
            | HITL approvals  |  money / sends / deletes block on a human
            +----------------+----------------+
            | evals: deterministic -> LLM judge -> prod sampling
            +----------------------------------+
```

## Quickstart

```bash
# 1. gateway
cd gateway && cp .env.example .env   # fill keys from the vault
docker compose up -d                 # -> http://localhost:4000

# 2. python env (from repo root)
pip install -r requirements.txt

# 3. deterministic tests (no gateway needed)
pytest evals/test_tools.py

# 4. Baraza 2.0 spike (gateway required)
export GATEWAY_URL=http://localhost:4000
export LITELLM_MASTER_KEY=sk-ansai-dev-local
python agents/baraza/run_weekly_cycle.py

# 5. LLM-judge a scenario (gateway required)
python evals/judge.py
```

## Layout

| Path | What |
|---|---|
| `gateway/` | LiteLLM proxy config, compose, run docs, failover test |
| `agents/` | mini worker, mother supervisor, handoff contract, Baraza 2.0 spike |
| `mcp/whatsapp/`, `mcp/mpesa/` | MCP tool servers (**stubs** — contracts stable, bodies TODO) |
| `skills/sacco-member-onboarding/` | packaged workflow a mini agent executes |
| `policy/` | HITL approval queue + human CLI |
| `evals/` | 3-layer eval skeleton (deterministic / judge / prod sampling) |
| `ARCHITECTURE.md` | the design thesis |
| `ROADMAP.md` | phased build plan with done-when criteria |
| `COSTS.md` | burn tracking under a tight budget |

## What is real vs stub

- **Real:** gateway config (needs keys + docker to run), agent code, handoff
  contract, approval queue, deterministic tests, judge runner.
- **Stub:** WhatsApp + M-Pesa tool bodies (marked STUB, TODOs inline),
  prod traffic sampler, scenario agent_outputs (canned until live generation).
- **Not started:** real WhatsApp/Daraja wiring, blackboard writer, Postgres
  log DB, per-group virtual keys (procedure documented, created post-boot).

See ROADMAP.md for the order everything goes live.
