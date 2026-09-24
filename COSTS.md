# COSTS — burn tracking under a tight budget

Starting position, verified 2026-09-24: **DeepSeek balance $2.59** (dev-scale),
Gemini key live. The architecture defaults to DeepSeek because the spend is
already covered — but $2.59 disappears fast if nothing watches it. Burn-tracking
is critical path.

## The caps

| Scope | Cap | Notes |
|---|---|---|
| Proxy-wide (`max_budget` in litellm-config.yaml) | $2.00 | hard stop; leaves $0.59 headroom on the $2.59 |
| `workhorse` virtual key | $1.20 | mini-agent loops — the biggest burner |
| `thinker` virtual key | $0.30 | supervision/planning — low volume |
| `vision` virtual key | $0.30 | multimodal + fallback traffic |
| `judge` virtual key | $0.20 | eval verdicts — capped by max_tokens=1000 |

Alerts at **50% and 80%** per key (LiteLLM alerting -> Slack/email/webhook;
configure per current LiteLLM docs). An 80% alert means: stop, look at the logs,
decide whether the spend taught us something before continuing.

## How spend is tracked

- The gateway logs every request to Postgres (local compose service, or
  Supabase on a VPS). Per-key spend is visible in the LiteLLM UI and API —
  that is the source of truth, not estimates. (SQLite is not an option:
  litellm >= 1.102 refuses it for DB features.)
- `max_tokens` per group in the config is a guardrail, not a budget: it bounds
  the worst single call, the key budgets bound the total.
- The judge group is deliberately the cheapest path: evals must be cheap enough
  to run constantly, or they won't run.

## What the gateway does NOT cover

- **Meta's WhatsApp per-message billing** (in-window service messages billed
  from Oct 1, 2026; ~KSh 0.52/message in Kenya — verify current Meta pricing
  before launch). Track in the Meta dashboard, not here. Design rule stands:
  batch, be concise, resolve in-window.
- **M-Pesa transaction fees** — Daraja-side, tracked in the Daraja portal.

## When the $2.59 runs out

The gateway refuses new spend by design. Topping up is a conscious decision,
not an accident discovered in the invoice. Before topping up: check the logs —
which group burned it, and did the evals improve? Spend without learning is the
failure mode this file exists to prevent.
