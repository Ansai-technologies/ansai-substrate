# Agent build standards — multimodal agents (factory standard, 29 Oct 2026)

Distilled from Meta's legal-agent-workshop repo + the Hazi/Hazina build.
Every Ansai agent (Hazi, Baraza seats, Armada analysts, wallet agents,
future builds) is built to these, no exceptions:

1. **One audited record holds all state.** No scattered globals; every run's
   state, decisions and evidence live in one inspectable record.
2. **Serial loop, one tool per turn.** The model proposes ONE action; code
   disposes. No parallel tool spam, no free-running agents.
3. **Verification lives inside the committing tool.** Deterministic checks
   fail closed (bad sum → no commit); judgement checks fail open with a flag.
   A result that cannot be verified does not get committed silently.
4. **Extract once, cache by hash.** Documents/images are read once, cached by
   SHA-256; re-runs never re-pay or re-read.
5. **The model never supplies the numbers that must be right.** Rates, caps,
   thresholds and rules live in versioned config; arithmetic is code.
6. **Bounded refusal, then escalate.** MAX_TRIES then hand the human the
   problem list — never invent a record for a gap.
7. **Human sign-off is an external, audited write.** Approvals (packs,
   wallet payments, publishes) are explicit acts in the log, not vibes.
8. **Agents never fire payments.** Money moves only through the wallet core's
   policy gate + a human approval where the policy demands one.
9. **Failures degrade to questions.** A gap becomes a question or a flag in
   the output — never a hallucinated fill.
10. **Evals before promotion.** Promptfoo + DeepEval gates (factory stack)
    before any agent's change reaches production work.

Applied so far: Hazi/Hazina (all ten), wallet core v0.1 (3, 6, 7, 8),
Armada analysts (designed to 1, 2, 6, 9).

## Addendum v0.2 (29 Oct 2026 — from the newsletter mining, founder-ratified direction)
11. **Gateway shape for tools:** agents reach tools/models through ONE governed chokepoint — a registry of reviewed tool definitions plus a proxy that verifies, authorises, and audits every call (the shape Uber's Model/MCP Gateways and DoorDash's Agent Gateway converged on independently). No direct agent→tool side channels as the catalogue grows.
12. **Flows end at a decision:** agent outputs terminate in a binary human decision (Approve / Reject, or the domain equivalent) wherever a human is in the loop — Sentinel alerts, Baraza drafts, Store agent actions. Reports that end in prose are a design defect.
13. **Economics at list price:** unit economics are planned at unsubsidised list prices, and model spend is tiered per product with sign-off above the cap (the Uber control). Subsidised credits are a windfall, never a budget line.
14. **Every consequential decision writes its WHY.** At decision time, the audited record captures the inputs considered, the rule or policy applied, the alternatives rejected, and who approved — the blackboard for council matters, the product event log (`hz_events` pattern) for product matters. Current state is not enough: systems of record store what is true now, never why it became true, and that trace cannot be retrofitted afterwards (Foundation Capital's context-graph thesis). The trace is the compounding asset — and it is what Attest sells as decision lineage. A decision whose WHY is not in the record is unfinished work. (Added 29 Oct 2026, from the playbook research adoption #1.)
