# Architecture — ansai-substrate

## Thesis: one substrate, two surfaces

Ansai's Dira entry 01 says every artifact a company owns is infrastructure that
emits and ingests data, and the company stack runs: capture -> clean -> store ->
tools -> mini agent per person -> one mother agent over all. This repo is the
substrate that thesis runs on. Build it once; two surfaces consume it:

1. **Internal (Baraza 2.0):** Kiongozi as supervisor over department agents,
   running the company's own weekly cycle on the same gateway, tools, and evals
   we sell. Dogfood first — it becomes the demo.
2. **Product (client runtimes):** the SACCO WhatsApp runtime and whatever comes
   next — mini agents per staff role, a mother agent per company holding the
   full picture.

## Layers

**Gateway (LiteLLM proxy).** The only component that knows providers exist.
Agents address model *groups*: `workhorse` (DeepSeek chat — routine loops),
`thinker` (DeepSeek reasoner — planning, supervision), `vision` (Gemini flash —
multimodal + fallback), `vision-cheap` (Gemini flash-lite — cheapest fallback),
`judge` (DeepSeek chat — eval verdicts). Failover: any group can fall back to
Gemini flash, so a DeepSeek wobble is invisible to agents. Spend caps per group
via virtual keys; proxy-wide hard cap in config.

**Orchestration (Agno).** Mini agents are workers with tools; the mother agent
is a supervisor. The binding rule: the mother receives **structured summaries**
(`handoff.summarize_state` -> `{goal, facts, open_questions, proposed_next}`,
hard-capped at 1500 chars), never transcripts. Summaries are the cost control
that makes supervision viable; if a decision needs detail, the mother asks a
targeted follow-up instead of pulling the transcript.

**Tools (MCP servers).** One server per integration, uniform tool surface for
agents. WhatsApp and M-Pesa start as stubs with stable contracts so agents,
skills, and evals can be built now; real API wiring swaps the bodies later
without touching callers.

**Policy (HITL).** Money movement, outbound sends, and deletes block on a human
via a JSONL approval queue + CLI. This is enforced at the call site (the skill
and the server docstrings both require it), not left to agent goodwill.

**Evals (3 layers).** Deterministic pytest contracts (no network) -> LLM-judge
scenario runs against the gateway's `judge` group -> production traffic sampling
for continuous regression detection. Evals run before agents touch anything
real, and keep running after.

## Economics: DeepSeek-default, Gemini-fallback

The verified starting position (2026-09-24): DeepSeek balance **$2.59**
(dev-scale), Gemini key live. So the architecture's "DeepSeek default" stands,
but burn-tracking is critical path, not an afterthought:

- Default everything to DeepSeek groups — the spend is already covered.
- Escalate to stronger/more expensive handling only when evals prove a task
  class needs it (evidence, not vibes).
- Gemini flash is the reliability layer (multimodal + automatic fallback), not
  the spend layer — its free/affordable tier keeps the fallback cheap.
- Per-group virtual keys with hard budgets (workhorse $1.20 / thinker $0.30 /
  vision $0.30 / judge $0.20 = $2.00 of the $2.59), alerts at 50%/80%, proxy
  hard cap at $2.00. When the $2.59 is gone, the gateway refuses — by design.

No invented pricing anywhere here: the only numbers that matter are the ones
the gateway logs. See COSTS.md.
