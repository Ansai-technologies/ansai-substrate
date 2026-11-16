# BUILD-LOG — Daraja adapter behind settle() (29 Oct 2026)

Founder's order: build now. Credit rule followed: all code generated via the
Meta Model API (muse-spark-1.3), then verified locally by the full suite.

## Built

- **daraja.js** — Daraja (M-Pesa) callback adapter. Pure parsing, zero
  dependencies, no network, no I/O, no credentials, fires nothing.
  - `parseStkCallback` / `parseC2bCallback` — normalise the two documented
    Daraja shapes into one evidence shape
    `{ receipt, amount, to, time, resultCode, source, payer, ref }`.
  - `normaliseCallback` — detects the shape and dispatches; unrecognised
    payloads rejected as `malformed_payload`.
  - `createDarajaAdapter(wallet, { shortcode })` — `handleCallback(payload)`
    feeds exactly `{ receipt, amount, to, resultCode }` into
    `wallet.settle()`; parse failures never reach settle().
  - Named parse rejections: `malformed_payload`, `missing_receipt`,
    `invalid_amount`, `missing_destination`, `missing_result_code`.
  - STK specifics: destination comes from the configured shortcode (the STK
    payload carries none — the payment lands on the owner's own till);
    failed callbacks (no metadata, e.g. ResultCode 1032) parse as evidence
    and are rejected by settle() as `result_code`, on the record.
  - C2B specifics: `TransAmount` string parsed to a number; destination is
    `BusinessShortCode`; resultCode is 0 by definition of a confirmation.
  - Daraja timestamps (YYYYMMDDHHmmss) converted to ISO/UTC with real-date
    validation.
- **daraja.fixtures.js** — sandbox-shaped factory payloads: STK success,
  STK failed (1032, no metadata), STK success without metadata, C2B success,
  C2B wrong amount, C2B wrong destination, C2B bad amount, and three
  malformed shapes. No real receipts, no real money.
- **daraja.test.js** — 14 tests: parse normalisation for both shapes,
  every named rejection, and the full chains — authorise → callback →
  settled; approval queue (early callback refused `not_approved`, settles
  after approval); wrong amount (`amount_mismatch`, authorisation
  survives); wrong destination (orphan, logged, never settled); duplicate
  delivery (`duplicate_receipt`); failed STK (`result_code`); malformed
  payloads never reaching settle(); kill switch refusing evidence.

## Test results

- Full suite (`node --test`, this folder): **29/29 pass** — 15 pre-existing
  wallet-core tests unchanged and passing, plus the 14 new adapter tests.
- `node --check` clean on all three new files.

## Generation note

Spark spent most of each budget on reasoning (8k-token calls returned null
content at `finish=length`); generation succeeded with a 24k-token ceiling
(10,229 reasoning + ~2k content for daraja.js). Verified output, no hand
edits needed.

## Left / not in this slice

- No live Daraja wiring: no credentials, no callback endpoint, no STK push.
  The adapter consumes payloads; what delivers them (and any payment
  execution behind an approved `authorise()`) remains behind the founder
  approval gate, per the wallet-core README boundary.
- C2B validation callbacks and B2C result/timeout shapes are out of scope
  for v0.1 of the adapter.
