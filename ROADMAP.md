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
- Run the Baraza 2.0 spike end to end; inspect Jabari's brief for handoff
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

### Shipped 2026-09-25 (ahead of schedule): first real tool servers
- `mcp/github/` — real GitHub REST tools (list/read issues+PRs, search code;
  create_issue/comment gated by HITL). Needs `GITHUB_TOKEN` in gateway/.env.
- `mcp/web/` — read-only internet: `web_search` (DuckDuckGo, no key),
  `fetch_page` (extract readable text).
- `mcp/local/` — local-machine access: sandboxed to `AGENT_LOCAL_ROOT`
  (default: repo root); credential files refused; `delete_file` and
  `run_command` always ask approval (small read-only allowlist skips it);
  every call audited to `policy/audit.jsonl` (gitignored).
- `agents/tools_registry.py` — `scout` (read-only) vs `worker` (+gated writes)
  profiles; `agents/run_worker.py` runs one worker with tools, visible live
  in the office at http://localhost:8080.
- **Done-when:** `pytest evals/test_tools.py` green; a worker run completes a
  read-only task (e.g. "summarize my open GitHub issues") with characters
  animating in the office and zero approval prompts.

## Phase 4 — Evals (weeks 3–4)

- `python evals/judge.py` runs all scenarios green; add scenarios for every
  new skill step.
- Wire `sample_prod.py` to the gateway log DB (Postgres — local compose
  service or Supabase).
- Set the quality bar: no agent ships a new capability with <2/2 on its
  scenario criteria.
- **Done-when:** judge suite green, prod sampler wired, bar documented.

## Phase 5 — Baraza 2.0, for real (weeks 4–6)

- Replace toy inputs with real department state; persist Jabari's brief
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

---

## Update — 2026-10-25: factory milestones and the road from here

Shipped (ahead of the phases below):

- **Factory v0.1 seed** — templates as standard, tool catalogue v1 (verified API pass), the ansai-utils MCP toolbox (4 tools, live-tested), REA (morluto/rea) adopted as the reverse-engineering tool.
- **Keys state:** Raindrop connected and verified. VirusTotal stored (verification owed — network reachability from the build VM). WolframAlpha and remove.bg hold invalid values (fix paths recorded in `factory/README.md`). Clipdrop's host refuses the credential-capture flow. Printful and Semantic Scholar not yet started.

The road from here, in order (each with its done-when):

1. **Gateway live on our ground** — LiteLLM stood up per `gateway/` on DC-01/Lenovo with virtual keys and budgets. Done-when: an agent in this repo makes a model call that appears in the gateway log.
2. **First agent born from the template** — the bursar agent, scaffolded from `templates/agent.template.yaml`, passing the Promptfoo + DeepEval gate. Done-when: the eval record is attested and the agent runs its first supervised cycle.
3. **REA installed in the factory** and the Baraza agents given the catalogue toolboxes (ansai-utils + REA). Done-when: a council cycle uses a catalogue tool and the call is in the record.
4. **Tool gateway** — catalogue servers behind one metering, policy-enforcing door, calls attested. Done-when: an external agent can be granted scoped, metered access.
5. **Daraja production + SACCO pilot** — the phases below then proceed as written, on production rails.

