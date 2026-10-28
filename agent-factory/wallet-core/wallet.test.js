"use strict";
/**
 * wallet.test.js — node:test suite for the Agent Wallet Core v0.1.
 * Run: node --test   (from this folder; Node 20+, no dependencies)
 */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { Wallet } = require("./wallet");
const { AuditLog } = require("./audit");

// A fixed clock makes expiry and UTC daily-cap behaviour deterministic.
const FIXED_NOW = () => new Date("2026-10-29T09:00:00.000Z");

function makeWallet(overrides = {}, options = {}) {
  const policy = {
    owner: "Ansai Technologies",
    agentId: "bursar-1",
    rail: "mpesa",
    perTxnCap: 10000,
    dailyCap: 50000,
    allowlist: ["600987", "123456"],
    approvalThreshold: 5000,
    expiresAt: "2027-01-01T00:00:00.000Z",
    killSwitch: false,
    ...overrides,
  };
  return new Wallet(policy, { now: FIXED_NOW, ...options });
}

test("happy path: authorise under threshold, then settle on Daraja evidence", () => {
  const w = makeWallet();
  const a = w.authorise({ to: "600987", amount: 1500, ref: "INV-1" });
  assert.equal(a.decision, "approved");

  const s = w.settle({ receipt: "QK123", amount: 1500, to: "600987", resultCode: 0 });
  assert.equal(s.settled, true);
  assert.equal(s.authorisationId, a.authorisationId);
  assert.equal(w.authorisations.get(a.authorisationId).state, "settled");
  assert.equal(w.audit.verify(), true);
});

test("over the per-transaction cap is denied", () => {
  const w = makeWallet();
  const a = w.authorise({ to: "600987", amount: 10001 });
  assert.equal(a.decision, "denied");
  assert.equal(a.reason, "over_per_txn_cap");
});

test("a destination outside the allowlist is denied", () => {
  const w = makeWallet();
  const a = w.authorise({ to: "999999", amount: 100 });
  assert.equal(a.decision, "denied");
  assert.equal(a.reason, "not_allowlisted");
});

test("at the approval threshold: queued, human approves, then settles", () => {
  const w = makeWallet();
  const a = w.authorise({ to: "123456", amount: 5000 }); // exactly at threshold
  assert.equal(a.decision, "needs_approval");
  assert.ok(a.approvalId);

  // Evidence arriving before approval must not settle it.
  const early = w.settle({ receipt: "QK200", amount: 5000, to: "123456", resultCode: 0 });
  assert.equal(early.settled, false);
  assert.equal(early.reason, "not_approved");

  const ok = w.approve(a.approvalId, "founder");
  assert.equal(ok.ok, true);

  const s = w.settle({ receipt: "QK200", amount: 5000, to: "123456", resultCode: 0 });
  assert.equal(s.settled, true);
  assert.equal(w.audit.verify(), true);
});

test("human denial resolves the queue and frees the daily-cap hold", () => {
  const w = makeWallet({ dailyCap: 6000 });
  const a = w.authorise({ to: "600987", amount: 5000 });
  assert.equal(a.decision, "needs_approval");
  assert.equal(w.dailyCommitted(), 5000); // reserved while pending

  const d = w.deny(a.approvalId, "founder");
  assert.equal(d.ok, true);
  assert.equal(w.dailyCommitted(), 0); // released on denial

  const s = w.settle({ receipt: "QK201", amount: 5000, to: "600987", resultCode: 0 });
  assert.equal(s.settled, false);
});

test("kill switch denies everything until lifted", () => {
  const w = makeWallet();
  w.setKillSwitch(true, "founder");
  const a = w.authorise({ to: "600987", amount: 100 });
  assert.equal(a.decision, "denied");
  assert.equal(a.reason, "kill_switch");

  w.setKillSwitch(false, "founder");
  const b = w.authorise({ to: "600987", amount: 100 });
  assert.equal(b.decision, "approved");
});

test("an initially-on kill switch (policy) denies from birth", () => {
  const w = makeWallet({ killSwitch: true });
  const a = w.authorise({ to: "600987", amount: 100 });
  assert.equal(a.decision, "denied");
  assert.equal(a.reason, "kill_switch");
});

test("an expired wallet denies", () => {
  const w = makeWallet({ expiresAt: "2026-01-01T00:00:00.000Z" }); // before FIXED_NOW
  const a = w.authorise({ to: "600987", amount: 100 });
  assert.equal(a.decision, "denied");
  assert.equal(a.reason, "expired");
});

test("a callback with the wrong amount is rejected; the authorisation survives", () => {
  const w = makeWallet();
  const a = w.authorise({ to: "600987", amount: 2000 });
  assert.equal(a.decision, "approved");

  const bad = w.settle({ receipt: "QK300", amount: 2001, to: "600987", resultCode: 0 });
  assert.equal(bad.settled, false);
  assert.equal(bad.reason, "amount_mismatch");
  assert.equal(w.authorisations.get(a.authorisationId).state, "approved");

  const good = w.settle({ receipt: "QK300", amount: 2000, to: "600987", resultCode: 0 });
  assert.equal(good.settled, true);
});

test("a non-zero result code is not evidence", () => {
  const w = makeWallet();
  w.authorise({ to: "600987", amount: 700 });
  const s = w.settle({ receipt: "QK400", amount: 700, to: "600987", resultCode: 1032 });
  assert.equal(s.settled, false);
  assert.equal(s.reason, "result_code");
});

test("an orphan callback is logged as an orphan and never settled", () => {
  const w = makeWallet();
  const s = w.settle({ receipt: "QK999", amount: 4242, to: "600987", resultCode: 0 });
  assert.equal(s.settled, false);
  assert.equal(s.reason, "orphan");
  const orphans = w.audit.entries.filter((e) => e.type === "settle_orphan");
  assert.equal(orphans.length, 1);
  assert.equal(orphans[0].data.receipt, "QK999");
  assert.equal(w.audit.entries.some((e) => e.type === "settle"), false);
});

test("daily cap is enforced across two payments", () => {
  const w = makeWallet({ dailyCap: 1000, approvalThreshold: Infinity });
  const a1 = w.authorise({ to: "600987", amount: 600 });
  assert.equal(a1.decision, "approved");
  const s1 = w.settle({ receipt: "QK500", amount: 600, to: "600987", resultCode: 0 });
  assert.equal(s1.settled, true);

  const a2 = w.authorise({ to: "600987", amount: 500 }); // 600 + 500 > 1000
  assert.equal(a2.decision, "denied");
  assert.equal(a2.reason, "over_daily_cap");

  const a3 = w.authorise({ to: "600987", amount: 400 }); // exactly to the cap
  assert.equal(a3.decision, "approved");
  assert.equal(w.dailyCommitted(), 1000);
});

test("every authorise call is audit-logged, including denials", () => {
  const w = makeWallet();
  w.authorise({ to: "600987", amount: 100 });
  w.authorise({ to: "999999", amount: 100 });
  const calls = w.audit.entries.filter((e) => e.type === "authorise");
  assert.equal(calls.length, 2);
  assert.equal(calls[1].data.decision, "denied");
});

test("hash chain verifies, and detects a tampered entry", () => {
  const log = new AuditLog({ now: FIXED_NOW });
  log.append("authorise", { authId: "auth_x", amount: 100, decision: "approved" });
  log.append("settle", { authId: "auth_x", amount: 100, receipt: "QK600" });
  log.append("kill_switch", { on: true, by: "founder" });
  assert.equal(log.verify(), true);

  // Rewrite history: inflate the settled amount after the fact.
  log.entries[1].data.amount = 100000;
  assert.equal(log.verify(), false);
});

test("hash chain detects a removed entry", () => {
  const log = new AuditLog({ now: FIXED_NOW });
  log.append("a", { n: 1 });
  log.append("b", { n: 2 });
  log.append("c", { n: 3 });
  log.entries.splice(1, 1);
  assert.equal(log.verify(), false);
});
