# Agent Wallet Core v0.1

The policy, permissions and evidence layer for an Ansai agent wallet — the
module that decides whether an agent *may* initiate a payment, queues a
human where the policy demands one, and later reconciles what the payment
rail *actually did*. Self-contained: Node 20+, no dependencies.

## Doctrine (five lines)

1. The wallet belongs to the organisation; the agent holds bounded permission, never custody.
2. The agent operates the owner's own till/paybill — funds never pass through the agent.
3. Caps, an allowlist, an approval threshold, an expiry and a kill switch bound every action.
4. Evidence of payment is a Daraja callback (result code 0) — never a screenshot, never an agent's word.
5. Every decision lands in a hash-chained audit log, so the record can be verified and tampering shows.

## Files

- `wallet.js` — the `Wallet` class: `authorise` / `approve` / `deny` / `settle` / `setKillSwitch`, plus `dailyCommitted()` replayed from the audit log.
- `audit.js` — append-only JSONL audit log (in-memory + optional file), each entry sha256-chained to the previous one; `verify()` detects edits, removals and reordering.
- `wallet.test.js` — `node --test` suite covering the happy path, every denial class, the approval queue, kill switch, expiry, callback mismatches, orphan callbacks, daily-cap enforcement and chain tampering.

## Mapping to `templates/wallet.template.json`

The template nests its fields; the core takes a flattened policy object.
The meaning is identical:

| Template (v0.1) | Wallet core policy |
|---|---|
| `owner` | `owner` |
| `operated_by_agent` | `agentId` |
| `rail.type` / `rail.instrument` / `rail.shortcode` | `rail` (descriptive; enforcement is on destinations, see below) |
| `policy.per_transaction_limit` | `perTxnCap` |
| `policy.daily_limit` | `dailyCap` |
| `policy.payee_allowlist` | `allowlist` (till/paybill numbers the agent may pay) |
| `policy.approval.above_amount` (+ approver/channel) | `approvalThreshold`; resolution via `approve(approvalId, by)` / `deny(approvalId, by)`, on record in the audit log |
| `policy.kill_switch` (described in prose) | `killSwitch` (initial boolean state) + `setKillSwitch(on, by)` |
| — (not in the template) | `expiresAt` (added by the core spec: a wallet that has expired denies everything) |
| `evidence.source_of_truth` | `settle()` accepts only Daraja-callback-shaped events: `{ receipt, amount, to, resultCode: 0 }` |

Two interpretation notes:

- The template says approval is required *above* an amount; the core requires
  it **at or above** `approvalThreshold`, so the threshold amount itself can
  never slip through unapproved.
- The template's `policy.active_hours` is not enforced by the core in v0.1;
  the flattened policy has no hours field. It belongs in a future policy
  extension, alongside the template's attestation hooks
  (`payment.matched` on match, hold-and-alert on unmatched — the core's
  orphan path is exactly that hold, minus the alert transport).

Behaviour worth knowing:

- A pending approval **reserves** its amount against the daily cap until it
  is denied, so the approval queue cannot be used to bypass `dailyCap`.
  Daily totals are computed by replaying the audit log by UTC date, from
  settled + approved (+ reserved) amounts.
- While the kill switch is on, `authorise()` denies everything and
  `settle()` refuses to process evidence.
- An unmatched callback is logged as an **orphan** and held for a human —
  never settled, never auto-released (the template's `on_unmatched` rule).

## Boundary — read this before wiring anything to it

**This module moves no money.** It initiates nothing: no STK push, no Daraja
API call, no credential, no network. It is the *governance* layer that a
future Daraja adapter plugs into — the adapter would sit behind `settle()`
(feeding real callbacks in as evidence) and behind an approved
`authorise()` (executing only what the policy and, where required, a human
have allowed).

Per factory doctrine, that adapter is a separate step and sits behind a
**founder approval gate**: agents never fire payments, and money movement is
only ever enabled by a filed approval plus the founder's explicit yes.
