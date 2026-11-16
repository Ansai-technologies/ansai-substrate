"use strict";
/**
 * wallet.js — Agent Wallet Core v0.1 (policy / permissions / evidence layer).
 *
 * Doctrine (templates/wallet.template.json): the wallet belongs to the
 * ORGANISATION. An agent operates it under bounded permission on the owner's
 * own till/paybill. The agent NEVER custodies funds and this module NEVER
 * fires a payment — it only decides, records and reconciles:
 *
 *   authorise()  — may the agent initiate this, under the policy?
 *   approve/deny — a human resolves anything at/above the approval threshold.
 *   settle()     — did the rail actually move the money? Only a
 *                  Daraja-callback-shaped event (resultCode 0) counts as
 *                  evidence. Never a screenshot, never an agent's claim.
 *
 * Every decision is written to a hash-chained audit log (audit.js). Daily
 * totals are computed by replaying that log, so the caps rest on the same
 * evidence a reviewer would inspect.
 */
const crypto = require("node:crypto");
const { AuditLog } = require("./audit");

const newId = (prefix) => prefix + crypto.randomBytes(6).toString("hex");

class Wallet {
  /**
   * @param {object} policy - flattened policy (see README for the mapping
   *   to wallet.template.json):
   *   { owner, agentId, rail, perTxnCap, dailyCap, allowlist: [till/paybill],
   *     approvalThreshold, expiresAt, killSwitch }
   * @param {object} [options]
   * @param {AuditLog} [options.audit] - supply your own log (default: new one).
   * @param {string} [options.auditPath] - JSONL path for the default log.
   * @param {Function} [options.now] - clock for tests; Date | ms | ISO string.
   */
  constructor(policy, options = {}) {
    if (!policy || typeof policy !== "object") {
      throw new TypeError("Wallet requires a policy object");
    }
    this.owner = policy.owner ?? null;
    this.agentId = policy.agentId ?? null;
    this.rail = policy.rail ?? "mpesa";
    this.perTxnCap = policy.perTxnCap ?? Infinity;
    this.dailyCap = policy.dailyCap ?? Infinity;
    this.allowlist = new Set((policy.allowlist || []).map(String));
    // At or above this amount a human must approve. Absent = never required.
    this.approvalThreshold = policy.approvalThreshold ?? Infinity;
    this.expiresAt = policy.expiresAt ? new Date(policy.expiresAt) : null;
    this.killSwitch = Boolean(policy.killSwitch);

    this._nowFn = options.now || (() => new Date());
    this.audit =
      options.audit ||
      new AuditLog({ filePath: options.auditPath || null, now: this._nowFn });

    this.authorisations = new Map(); // authId -> record
    this.approvals = new Map(); // approvalId -> { id, authId, state }
  }

  _now() {
    const t = this._nowFn();
    return t instanceof Date ? t : new Date(t);
  }

  _today() {
    return this._now().toISOString().slice(0, 10); // UTC date
  }

  _expired() {
    return this.expiresAt ? this._now().getTime() > this.expiresAt.getTime() : false;
  }

  /**
   * Amount committed on a UTC date, computed by replaying the audit log:
   * authorisations that are approved, settled, or pending approval (a
   * pending approval reserves against the cap until it is denied, so a
   * queue of requests cannot be used to slip past the daily limit).
   */
  dailyCommitted(dateStr = this._today()) {
    const states = new Map(); // authId -> { amount, date, state }
    for (const e of this.audit.entries) {
      const d = e.data || {};
      if (e.type === "authorise" && d.authId) {
        states.set(d.authId, {
          amount: d.amount,
          date: String(e.ts).slice(0, 10),
          state:
            d.decision === "approved"
              ? "approved"
              : d.decision === "needs_approval"
                ? "pending"
                : "denied",
        });
      } else if (e.type === "approval_approved" || e.type === "approval_denied") {
        const s = states.get(d.authId);
        if (s && s.state === "pending") {
          s.state = e.type === "approval_approved" ? "approved" : "denied";
        }
      } else if (e.type === "settle") {
        const s = states.get(d.authId);
        if (s) s.state = "settled";
      }
    }
    let total = 0;
    for (const s of states.values()) {
      if (
        s.date === dateStr &&
        (s.state === "approved" || s.state === "pending" || s.state === "settled")
      ) {
        total += s.amount;
      }
    }
    return total;
  }

  /**
   * Ask permission to initiate a payment of `amount` to `to` (a till/paybill
   * number). Returns exactly one of:
   *   { decision: "approved", authorisationId }
   *   { decision: "needs_approval", approvalId, authorisationId }
   *   { decision: "denied", reason, authorisationId }
   * Reasons: kill_switch | expired | invalid_amount | not_allowlisted |
   *          over_per_txn_cap | over_daily_cap
   * Every call — approved, queued or denied — is audit-logged.
   */
  authorise(req = {}) {
    const { amount, ref } = req;
    const to = req.to != null ? String(req.to) : null;
    const authId = newId("auth_");
    const logData = {
      authId,
      to,
      amount,
      ref: ref ?? null,
      agentId: this.agentId,
      owner: this.owner,
    };
    const deny = (reason) => {
      this.authorisations.set(authId, {
        id: authId, to, amount, ref: ref ?? null, state: "denied", reason,
      });
      this.audit.append("authorise", { ...logData, decision: "denied", reason });
      return { decision: "denied", reason, authorisationId: authId };
    };

    if (this.killSwitch) return deny("kill_switch");
    if (this._expired()) return deny("expired");
    if (typeof amount !== "number" || !Number.isFinite(amount) || amount <= 0) {
      return deny("invalid_amount");
    }
    if (!this.allowlist.has(to)) return deny("not_allowlisted");
    if (amount > this.perTxnCap) return deny("over_per_txn_cap");
    if (this.dailyCommitted() + amount > this.dailyCap) {
      return deny("over_daily_cap");
    }

    if (amount >= this.approvalThreshold) {
      const approvalId = newId("appr_");
      this.authorisations.set(authId, {
        id: authId, to, amount, ref: ref ?? null, state: "pending", approvalId,
      });
      this.approvals.set(approvalId, { id: approvalId, authId, state: "pending" });
      this.audit.append("authorise", {
        ...logData, decision: "needs_approval", approvalId,
      });
      return { decision: "needs_approval", approvalId, authorisationId: authId };
    }

    this.authorisations.set(authId, {
      id: authId, to, amount, ref: ref ?? null, state: "approved",
    });
    this.audit.append("authorise", { ...logData, decision: "approved" });
    return { decision: "approved", authorisationId: authId };
  }

  /** Human approval of a queued authorisation. Audit-logged either way. */
  approve(approvalId, by) {
    return this._resolveApproval(approvalId, by, true);
  }

  /** Human denial of a queued authorisation. Releases its daily-cap hold. */
  deny(approvalId, by) {
    return this._resolveApproval(approvalId, by, false);
  }

  _resolveApproval(approvalId, by, isApprove) {
    const type = isApprove ? "approval_approved" : "approval_denied";
    const ap = this.approvals.get(approvalId);
    if (!ap) {
      this.audit.append(type, {
        approvalId, authId: null, by: by ?? null, ok: false, reason: "unknown_approval",
      });
      return { ok: false, reason: "unknown_approval" };
    }
    if (ap.state !== "pending") {
      this.audit.append(type, {
        approvalId, authId: ap.authId, by: by ?? null, ok: false, reason: "already_resolved",
      });
      return { ok: false, reason: "already_resolved" };
    }
    ap.state = isApprove ? "approved" : "denied";
    const auth = this.authorisations.get(ap.authId);
    if (auth) auth.state = isApprove ? "approved" : "denied";
    this.audit.append(type, {
      approvalId, authId: ap.authId, by: by ?? null, ok: true,
    });
    return { ok: true, authorisationId: ap.authId };
  }

  /**
   * Reconcile a payment against rail evidence. `event` must be
   * Daraja-callback-shaped: { receipt, amount, to, resultCode: 0 }.
   * Settles only an APPROVED authorisation whose amount and destination
   * match exactly. Anything else is rejected and logged:
   *   - callback for a destination with an approved authorisation at a
   *     different amount  -> "settle_rejected" / amount_mismatch
   *   - callback matching a still-pending authorisation
   *                        -> "settle_rejected" / not_approved
   *   - non-zero resultCode -> "settle_rejected" / result_code
   *   - receipt already settled -> "settle_rejected" / duplicate_receipt
   *   - no matching authorisation at all -> "settle_orphan" / orphan
   *     (logged and held for a human; never settled, never auto-released)
   */
  settle(event = {}) {
    const { receipt, amount, resultCode } = event;
    const to = event.to != null ? String(event.to) : null;
    const base = { receipt: receipt ?? null, amount, to, resultCode };
    const reject = (type, reason, extra = {}) => {
      this.audit.append(type, { ...base, ...extra, reason });
      return { settled: false, reason };
    };

    if (this.killSwitch) return reject("settle_rejected", "kill_switch");
    if (resultCode !== 0) return reject("settle_rejected", "result_code");

    if (receipt != null) {
      for (const a of this.authorisations.values()) {
        if (a.state === "settled" && a.receipt === receipt) {
          return reject("settle_rejected", "duplicate_receipt", { authId: a.id });
        }
      }
    }

    let exact = null;
    let wrongAmount = null;
    let pending = null;
    for (const a of this.authorisations.values()) {
      if (a.to !== to) continue;
      if (a.state === "approved") {
        if (a.amount === amount) { exact = a; break; }
        wrongAmount = wrongAmount || a;
      } else if (a.state === "pending") {
        pending = pending || a;
      }
    }

    if (exact) {
      exact.state = "settled";
      exact.receipt = receipt ?? null;
      this.audit.append("settle", { ...base, authId: exact.id });
      return { settled: true, authorisationId: exact.id, receipt: receipt ?? null };
    }
    if (wrongAmount) {
      return reject("settle_rejected", "amount_mismatch", { authId: wrongAmount.id });
    }
    if (pending) {
      return reject("settle_rejected", "not_approved", { authId: pending.id });
    }
    return reject("settle_orphan", "orphan");
  }

  /**
   * Suspend or resume the wallet, on record. While the kill switch is on,
   * authorise() denies everything and settle() refuses to process evidence.
   */
  setKillSwitch(on, by) {
    this.killSwitch = Boolean(on);
    this.audit.append("kill_switch", { on: this.killSwitch, by: by ?? null });
    return { killSwitch: this.killSwitch };
  }
}

module.exports = { Wallet };
