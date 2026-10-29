# Standards audit — 29 Oct 2026

Audit of tonight's builds against **AGENT-STANDARDS.md v0.1 (rules 1–10)**.
Read-only: no code was changed. Verdicts: **COMPLIES / PARTIAL / VIOLATES /
NOT-APPLICABLE**, each with file + mechanism as evidence. Strictness rule
applied throughout: a rule honoured in a test, a docstring, or a prompt —
but not in the code path that commits — scores PARTIAL at best. v0.2
readiness (rules 11–13) is noted in one line per build, not audited.

---

## 1. Wallet core + Daraja adapter — `agent-factory/wallet-core/`

| # | Rule | Verdict | Evidence |
|---|------|---------|----------|
| 1 | One audited record | **COMPLIES** | `audit.js` — append-only, SHA-256 hash-chained log with `verify()`; every authorise/approval/settle/kill-switch decision is appended. `wallet.js dailyCommitted()` replays the log to compute caps, so the log — not the in-memory Maps — is authoritative for the numbers that matter. |
| 2 | Serial loop, one tool per turn | **NOT-APPLICABLE** | No model or tool loop exists; this is a deterministic policy library an agent calls. |
| 3 | Verification inside the committing tool | **COMPLIES** | `wallet.js settle()` settles only an APPROVED authorisation with exact amount + destination match and `resultCode === 0`; duplicates, amount mismatches, pending and orphan callbacks are rejected with named reasons and logged. `daraja.js` validates receipt/amount/destination before evidence reaches `settle()`, and never does I/O. (Minor: `settle()` itself tolerates `receipt: null`; the adapter is what guarantees a receipt in the real path.) |
| 4 | Extract once, cache by hash | **NOT-APPLICABLE** | No document/image extraction in this build. |
| 5 | Model never supplies the numbers | **COMPLIES** | No model anywhere. Caps, allowlist, approval threshold and expiry arrive as the policy object (config); all arithmetic (daily-cap replay) is code. |
| 6 | Bounded refusal, then escalate | **COMPLIES** | `authorise()` denies with named bounded reasons (kill_switch, expired, invalid_amount, not_allowlisted, over_per_txn_cap, over_daily_cap); anything at/above threshold escalates to a human approval queue; orphan settlements are held for a human, never settled or auto-released. |
| 7 | Human sign-off is an audited write | **COMPLIES** | `approve()`/`deny()` resolve only pending approvals, record `by`, and append `approval_approved`/`approval_denied` entries (including failed attempts: unknown_approval, already_resolved). |
| 8 | Agents never fire payments | **COMPLIES** | The module never fires a payment — no network, no credentials, no I/O in `daraja.js`; `wallet.js` only decides, records and reconciles. Money movement is outside the build by construction. |
| 9 | Failures degrade to questions | **COMPLIES** | Every failure path returns a named rejection and writes it to the log; unverifiable evidence becomes a held orphan record for a human — never a fabricated settlement. |
| 10 | Evals before promotion | **PARTIAL** | A real gate-analogue exists — `wallet.test.js` + `daraja.test.js` suites (29 checks) — but the named gate (Promptfoo + DeepEval) is absent and inapplicable to non-LLM code; nothing wires the suite into a promotion step. |

**Counts:** COMPLIES 7 · PARTIAL 1 · VIOLATES 0 · N/A 2
**v0.2 readiness:** Closest of the six — authorise() already terminates in a binary decision (approved / needs_approval / denied, rule 12) and the wallet is a governed chokepoint for money; no tool/model gateway (rule 11) exists yet — agents would import these functions directly.

---

## 2. Hazina product + Hazi — `hazina-app/` + `hazina-agent-hackathon/`

| # | Rule | Verdict | Evidence |
|---|------|---------|----------|
| 1 | One audited record | **COMPLIES** | Pipeline: `agent/record.py` — one JSON record per run (documents, transactions, matches, questions, actor-stamped log, hash-stamped decisions). Product: `hz_*` tables per month + `hz_events` actor-stamped log (`api/data.js`, `api/_lib.js logEvent`). |
| 2 | Serial loop, one tool per turn | **COMPLIES** | No free-running agent loop exists. `run_month.py` is a fixed serial pipeline (ingest → extract → match → ask → compute → pack); each model call is a single bounded step invoked by code (one vision call per receipt in `extract_receipt.run`, one single-shot call per owner question in `api/ask.js`). The model never selects actions. |
| 3 | Verification inside the committing tool | **VIOLATES** | See violations list — the pipeline's deterministic sum check fails open, and the product's committing endpoints do not re-verify. |
| 4 | Extract once, cache by hash | **PARTIAL** | Pipeline complies fully: `record.py register_document/cached_extraction` — documents registered by SHA-256, extractions cached against the hash, never re-paid. Product does not: `api/extract.js` is stateless — no cache lookup before the vision call, so re-uploading the same receipt re-pays; hashes are recorded at save time and in pack inputs (`api/data.js save_pack`) but never consulted first. |
| 5 | Model never supplies the numbers | **PARTIAL** | Rates and arithmetic are config + code on both halves (`agent/rules.py` reads only `config/`; `api/_lib.js` loads `rules.ke.json`, `compute()` does the arithmetic, Ask Hazi is fed code-computed figures verbatim). But: the question threshold is a code literal — `QUESTION_THRESHOLD_KES = 1000` in `run_month.py` — and `_lib.js` embeds a full duplicate set of fallback tax constants (TOT_RATES, BANDS, relief, VAT threshold, company rate) plus a literal `0.015` default in `totRate()`, all free to drift silently from `rules.ke.json`. |
| 6 | Bounded refusal, then escalate | **PARTIAL** | Escalation is real and in the code path — `agent/ask.py escalate_unanswered` converts unanswered questions to explicit pack flags and `finalise_gate` blocks finalisation on open ones. But `MAX_ROUNDS = 3` is declared and written into the escalation log line ("unanswered after 3 rounds") while the pipeline actually runs one ask/answer pass — the bound is asserted, not iterated. In the product there is no bounded-ask at all: open questions ride into a locked month as flags (`lock_month` logs the count). |
| 7 | Human sign-off is an audited write | **COMPLIES** | Product: `lock_month` refuses to lock without a saved pack (409), then writes the merchant's approval into `hz_events` ("Month approved and locked by the merchant…"); closed months refuse further edits (409). Pipeline: merchant answers are human-stamped record writes, decisions are hash-stamped, and the pack is never filed by Hazi — a human files on iTax. (Observation: the pipeline's `finalise_gate` is advisory — computed and printed while `write_pack` runs regardless; acceptable only because the pack is not the filing.) |
| 8 | Agents never fire payments | **COMPLIES** | No payment or filing capability exists anywhere in either half; `pack.py`/`packText` state it in the artefact itself: "A human files on iTax; Hazi never submits." |
| 9 | Failures degrade to questions | **COMPLIES** | Thin statement lines become merchant questions (`run_month.py`); unmatched receipts/lines stay visible and are put to the merchant (`match.py`, `ask.py`); eTIMS defaults to `False` "unless evidenced"; Ask Hazi's instructions require naming what is missing rather than inventing it — and the model there has no write path at all. |
| 10 | Evals before promotion | **PARTIAL** | A genuine custom harness exists and passes — `eval/run_eval.py` grades the real pipeline against `ground_truth.json` plus three deterministic failure cases (`eval/results-latest.md`: extraction 15/15, TOT exact, bad-sum/unanswered cases pass), and `live-e2e.js` covers the product. But Promptfoo + DeepEval are not used, and no eval result gates a deploy. |

**Counts:** COMPLIES 5 · PARTIAL 4 · VIOLATES 1 · N/A 0
**v0.2 readiness:** Rule 12 is half-built — questions terminate in merchant answers and the month terminates in the merchant's lock decision; rule 13 is unmetered in the product (the pipeline records per-extraction token usage in the record; the product records none); rule 11 absent — tools are called directly by pipeline code.

---

## 3. Ansai ID — `ansai-id/`

| # | Rule | Verdict | Evidence |
|---|------|---------|----------|
| 1 | One audited record | **COMPLIES** | All state lives behind one store interface in four tables (`id_people`, `id_enrolments`, `id_agent_bindings`, `id_step_up_events`); `src/identity.js` + `src/bindings.js` are stateless functions over that store — no scattered state. (Deploy caveat: `server.js` falls back to the in-memory store when Supabase env is absent; the runbook's health check exists to catch exactly that.) |
| 2 | Serial loop | **NOT-APPLICABLE** | No model, no tools, no agent loop — a deterministic identity service. |
| 3 | Verification inside the committing tool | **COMPLIES** | `bindings.js createBinding()` refuses to commit a binding for a human with no enrolment (throws). `authorizeGatedAction()` fails closed: inactive/expired binding or no fresh approved step-up (≤300 s) → `{allowed:false}` with a named reason. Credential checks use `timingSafeEqual` (`identity.js`). |
| 4 | Extract once, cache by hash | **NOT-APPLICABLE** | No extraction; hashes here are credential/proof digests, not document reads. |
| 5 | Model never supplies the numbers | **NOT-APPLICABLE** | No model. (Note: the one policy number, the 300-second step-up freshness window, is a code default parameter in `authorizeGatedAction` — `maxAgeSeconds=300` — not config.) |
| 6 | Bounded refusal, then escalate | **PARTIAL** | Refusals are named and fail-closed, and the step-up event is the escalation path. But there is no bounded-try counter: `/authorize` can be re-presented indefinitely — bounded in practice only because each allowance needs a fresh approved step-up from the bound human. |
| 7 | Human sign-off is an audited write | **COMPLIES** | This service *is* the sign-off substrate: step-up approvals are persisted `id_step_up_events` rows with proof hash, result and person; `server.js POST /step-ups` requires the bound human's own session (403 otherwise). (Observation: `POST /authorize` is unauthenticated — it commits nothing and returns only allowed/reason, but any caller can probe a binding's state.) |
| 8 | Agents never fire payments | **NOT-APPLICABLE** | No money surface exists in the build. |
| 9 | Failures degrade to questions | **NOT-APPLICABLE** | No generative surface; errors are explicit throws / named denial reasons — flagged here as N/A rather than compliance credit. |
| 10 | Evals before promotion | **PARTIAL** | `test/identity.test.js` + `test/bindings.test.js` (5/5) and `scripts/smoke.js` (16/16 against the local service) exist and pass; no Promptfoo/DeepEval (inapplicable to non-LLM code) and no gate wired to the (not yet performed) deploy. |

**Counts:** COMPLIES 3 · PARTIAL 2 · VIOLATES 0 · N/A 5
**v0.2 readiness:** Supplies the identity half of rule 11 (bindings + step-up are what a gateway would consult) but is not itself a gateway or proxy; rules 12–13 do not apply to its surface.

---

## 4. Armada A0+A1 — `armada/`

| # | Rule | Verdict | Evidence |
|---|------|---------|----------|
| 1 | One audited record | **COMPLIES** | One append-only store (`data/events.jsonl`, deduped by event id in `lib.js appendEvents`) holds all collected state; `data/audit.jsonl` logs every fetch cycle (`collect.js`) and every dome query/lookup (`server.js` audits `/api/events`, `/api/entities`, `/api/entity`, `/api/exposure`). |
| 2 | Serial loop | **NOT-APPLICABLE** | No agent exists yet — A0/A1 are collectors plus deterministic entity extraction; collection itself runs serially (`collect.js` awaits each source in turn). The standards' "Armada analysts" are designed, not built. |
| 3 | Verification inside the committing tool | **PARTIAL** | Guards live in the collectors, ad hoc: GDELT checks zip magic bytes, row width (≥61 fields) and a non-empty source URL (`collectors.js`); OpenSky skips null coordinates. But the commit path itself — `appendEvents` — verifies only that an event has an id and is not a duplicate; there is no schema validation at the point of commit, and USGS mapping assumes `geometry` exists (a malformed feature fails the whole source rather than the row). |
| 4 | Extract once, cache by hash | **NOT-APPLICABLE** | No document extraction or model reads; feeds are re-polled streams by design, with id-dedupe preventing re-storage. |
| 5 | Model never supplies the numbers | **NOT-APPLICABLE** | No model. Figures in the dome are counts computed in code over the store (`entities.js buildIndex`). |
| 6 | Bounded refusal, then escalate | **PARTIAL** | Failure is bounded per source — a throwing collector is caught, audit-logged `ok:false`, and the cycle completes with the other sources (`collect.js`). But nothing escalates to a human: a dead source is visible only if someone opens the audit log or dome. No alert path exists yet (Sentinel integration is a later slice). |
| 7 | Human sign-off | **NOT-APPLICABLE** | No approvals or sign-offs exist in a collector/dome build. |
| 8 | Agents never fire payments | **NOT-APPLICABLE** | No money surface exists in the build. |
| 9 | Failures degrade to questions | **PARTIAL** | Mostly disciplined: missing values stay null (OpenSky skips, GDELT lat/lon → null), failed fetches produce audit entries, not invented events. One breach: `collectGdelt` substitutes the *collection* time (`new Date().toISOString()`) as the event's time when the source timestamp is malformed — an invented figure in the record, unflagged. |
| 10 | Evals before promotion | **PARTIAL** | The weakest of the six: there is **no automated test suite at all** in `armada/` — verification to date is manual proof runs recorded in `BUILD-LOG.md`. No eval gate of any kind stood between changes and the running collector. (Promptfoo/DeepEval themselves are inapplicable; nothing took their place.) |

**Counts:** COMPLIES 1 · PARTIAL 4 · VIOLATES 0 · N/A 5
**v0.2 readiness:** Not ready on rule 12 — entity and exposure outputs end in lists in the dome, not in a human decision (the intended decision surface, Sentinel alerts, is a later slice); rules 11/13 do not bite yet (no agents, no model spend).

---

## 5. Agent Store slices 1+2 — `agent-store/`

| # | Rule | Verdict | Evidence |
|---|------|---------|----------|
| 1 | One audited record | **PARTIAL** | One store abstraction (`api/_store.js` over file or Supabase `as_*` tables) and one provisioning record per order holding spec, pricing, payment and status (`api/_spec.js buildRecord`). But the record is mutable state with timestamps, not an audited trail — status overwrites; there is no append-only event log per record. |
| 2 | Serial loop | **NOT-APPLICABLE** | No agent runtime exists yet — the store provisions agent *specs*; nothing executes. (The specs declare the intended shape: policy may/must_approve/never lists in `buildRecord`.) |
| 3 | Verification inside the committing tool | **PARTIAL** | `api/_paycore.js applyCallback()` — the function that commits provisioning — verifies `ResultCode === 0` and exact amount equality before setting `provisioned`; a wrong amount flags the record (`payment_flagged`) and never provisions. Gaps: no duplicate/replay guard (a replayed confirmed callback re-enters `applyCallback` unchecked — the payment's own status is never tested), no receipt-uniqueness check, and evidence-checking is a parallel implementation rather than the wallet core's `settle()`. All forgivable only because the rail is still the bannered stub. |
| 4 | Extract once, cache by hash | **NOT-APPLICABLE** | No extraction in the build. |
| 5 | Model never supplies the numbers | **COMPLIES** | No model anywhere in the flow. Prices come from the versioned job modules (`api/_job_*.js`, e.g. Job Hunter passes 199/399 with fixed allowances); totals are code arithmetic (`totalKes` = pass price, or setup + monthly); customer policy numbers (daily cap, approval threshold, payees) are validated as positive/present in `_spec.js parsePolicy` before a record can exist. |
| 6 | Bounded refusal, then escalate | **NOT-APPLICABLE** | No agent executes, so there is nothing to refuse yet; the never-a-dead-end behaviour is catalogue copy in the job definitions, untestable until runtimes land. |
| 7 | Human sign-off is an audited write | **PARTIAL** | The one consequential transition (→ `provisioned`) is evidence-gated and timestamped on the record, and an admin view exists (`api/admin.js`). But there is no append-only sign-off/approval log, and the specs' `must_approve` rules are unenforced declarations until agent runtimes exist. |
| 8 | Agents never fire payments | **COMPLIES** | No real payment can fire: the STK request is an explicitly bannered stub (`api/_paycore.js buildStkRequest` — `stub: true`, "No network call was made. No charge occurred", callback URL on an `.invalid` domain); confirmation is either the simulator or a callback-shaped POST. No Daraja credentials or network payment call exist in the codebase. |
| 9 | Failures degrade to questions | **COMPLIES** | Every gap is an explicit error, never an invention: unknown job, missing required answer, unchosen pass, invalid policy all return named 400s (`api/provision.js`, `parsePolicy`). The one placeholder — `bound_human: "ansai-id:pending-enrolment"` — is labelled pending, not asserted as a real binding. |
| 10 | Evals before promotion | **PARTIAL** | `tests/e2e.js` (42/42, including the Supabase proof run) gated both PRs and passes on the merged shape; no Promptfoo/DeepEval (no LLM surface exists yet to eval) and the suite is a manual run, not a wired promotion gate. |

**Counts:** COMPLIES 3 · PARTIAL 4 · VIOLATES 0 · N/A 3
**v0.2 readiness:** v0.2-shaped on paper only — every spec already declares a gateway alias and a token budget with an on-cap behaviour (`model: {gateway_alias, budget:{daily_token_cap, on_cap:"pause"}}` in `buildRecord`), rule 13's fields exist before any runtime does; nothing enforces them yet, and rule 12's decisions belong to the future runtimes.

---

## 6. Baraza Room — `makao-makuu-app/api/_room.js`, `room.js`, `room-draft.js`

| # | Rule | Verdict | Evidence |
|---|------|---------|----------|
| 1 | One audited record | **PARTIAL** | State is split across two records by design: the thread store (`room_messages` in Supabase) and the council blackboard (GitHub `council/log.md`). Founder messages are mirrored to the blackboard (`room.js POST` → `appendBlackboard`, with `blackboard_ref` recorded as appended/skipped on the message row). Seat drafts are **not** mirrored — they exist only in `room_messages` — so the blackboard, the council's record of record, does not hold the whole conversation. |
| 2 | Serial loop, one tool per turn | **COMPLIES** | Drafting is one bounded model call per human request (`_room.js draftReply`); the output is stored as a draft and a human chairs from there. No loop, no parallel tool calls, no auto-send — the model proposes, the founder disposes. |
| 3 | Verification inside the committing tool | **PARTIAL** | Drafts are committed to `room_messages` (`room-draft.js`, `source: 'draft'`) with no verification of content against the record before the write. The mitigation is real — the `draft` label and the human chair — but nothing checks a draft that misstates the blackboard before it lands in the thread. |
| 4 | Extract once, cache by hash | **PARTIAL** | The build's core document — the blackboard — is re-read in full on every draft request and every founder message (`readBlackboard()` fetches the whole `council/log.md`, ~420K chars). The GitHub response's `sha` is captured and returned by `readBlackboard` but never used: no cache, no conditional fetch. Model cost is bounded (only a 6,000-char tail is sent), but the read itself is re-paid in full every time. |
| 5 | Model never supplies the numbers | **PARTIAL** | There are no rates/caps/thresholds in this build for a model to supply, and grounding is record-only (blackboard tail + thread are the model's whole world; the prompt forbids inventing facts). But figure fidelity in a draft rests entirely on that prompt — no code checks numbers in a draft against the record. |
| 6 | Bounded refusal, then escalate | **PARTIAL** | `draftReply` makes exactly one attempt; failures return a named reason (`model call failed`, `empty draft`) and store nothing. Bounded by construction, and the human is already in the loop — but there is no retry bound or escalation structure in code; the pattern exists by circumstance, not by mechanism. |
| 7 | Human sign-off is an audited write | **PARTIAL** | The founder's own messages are audited writes (thread row + GitHub commit to the blackboard). Drafts are never auto-promoted by any endpoint here. But there is no sign-off act in the API surface: no approve/edit/send transition for a draft exists in these files — the draft sits in the thread as a message authored by the seat, and what makes it "sent" lives outside the audited surface (slice-1 scope). |
| 8 | Agents never fire payments | **NOT-APPLICABLE** | No money surface exists in the build. |
| 9 | Failures degrade to questions | **COMPLIES** | The drafting prompt instructs: "Do not invent facts beyond them; if the record does not answer, say plainly what is missing." Empty or failed drafts produce a reason and no stored text — never a fabricated reply. |
| 10 | Evals before promotion | **PARTIAL** | Verified by local dry-run checks (15/15 at build time) and a live blackboard read; no eval suite exists for draft quality, no Promptfoo/DeepEval, and the switch-on (SQL + keys + deploy) will promote it with no gate in between. |

**Counts:** COMPLIES 2 · PARTIAL 7 · VIOLATES 0 · N/A 1
**v0.2 readiness:** Rule 12 is satisfied by posture — every draft terminates at the founder's decision, nothing auto-acts; rule 11 is not — seats call the model API directly from the route handler, no gateway or registry stands between.

---

## Violations list (severity order, smallest fix for each)

**V1 — Hazina, Rule 3: deterministic verification fails open, and the product's commits don't re-verify.**
Severity: highest in this audit — it is the only place an unverified, must-be-right figure enters a record of record.
- (a) `hazina-agent-hackathon/agent/tools/extract_receipt.py`: the in-tool cross-check (line items vs total) is deterministic, and on failure the transaction **is still committed** at the model-stated total — confidence drops to 0.5 and a question is added, but rule 3's own example is "bad sum → no commit."
  *Smallest fix:* on `cross_check != "ok"`, skip `add_transaction` and record only the flagged extraction + the question (keyed by document sha); the transaction is created when the merchant answers.
- (b) `hazina-app/api/extract.js`: the product extraction endpoint has **no sum cross-check at all** — it returns the model's JSON verbatim.
  *Smallest fix:* port the pipeline's five-line items-sum check into `extract.js` and return the mismatch as an explicit flag in the response.
- (c) `hazina-app/api/data.js` (`reconcile` action): receipt↔statement matches computed on the client are committed verbatim; the server never re-checks amount/date agreement.
  *Smallest fix:* in the `reconcile` handler, re-verify each submitted pair against `hz_txns`/`hz_receipts` (amount equality + date window, mirroring `match.py`) and drop non-conforming pairs from the commit.

No other build carries a VIOLATES verdict. The most consequential PARTIALs, for the record: Armada rule 10 (no test suite at all), Hazina rule 6 (`MAX_ROUNDS` asserted in the log but never iterated), Baraza Room rule 4 (blackboard re-read in full per request, sha unused), Agent Store rule 3 (no callback replay guard — must land before the real Daraja rail does).
