"use strict";
/**
 * checkpoint.js — human checkpoint for cross-fence agent actions.
 *
 * Doctrine:
 * - An agent whose work must cross a fence (another department, or a higher
 *   job tier) cannot proceed on its own say-so. It files a PROPOSAL.
 * - A human decides. Only an approved proposal yields an executable token.
 * - Every decision must record WHY it was made. A decision whose why is not
 *   in the record is unfinished work: `decide` refuses to record without it.
 * - No self-approval: the person whose agent is asking cannot decide it.
 * - Persistence is an append-only JSONL event file. Events are
 *   `proposal_created` and `proposal_decided`. State is derived by folding
 *   events on load; the file is never rewritten.
 */
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

/**
 * @param {*} v
 * @returns {boolean}
 */
function isNonEmptyString(v) {
  return typeof v === "string" && v.length > 0;
}

/**
 * @param {*} v
 * @returns {boolean}
 */
function isPlainObject(v) {
  if (typeof v !== "object" || v === null || Array.isArray(v)) {
    return false;
  }
  const proto = Object.getPrototypeOf(v);
  return proto === Object.prototype || proto === null;
}

/**
 * @param {*} v
 * @returns {*}
 */
function deepCopy(v) {
  return JSON.parse(JSON.stringify(v));
}

/**
 * @param {string} code
 * @param {string} message
 * @returns {never}
 */
function fail(code, message) {
  const err = new Error(message);
  err.code = code;
  throw err;
}

class ProposalStore {
  /**
   * @param {string} filePath
   * @param {{ now?: () => Date }} [options]
   */
  constructor(filePath, options) {
    if (!isNonEmptyString(filePath)) {
      fail("ERR_INVALID_ARGUMENT", "filePath must be a non-empty string");
    }
    const opts = options || {};
    let nowFn = () => new Date();
    if (typeof opts.now !== "undefined") {
      if (typeof opts.now !== "function") {
        fail("ERR_INVALID_ARGUMENT", "options.now must be a function");
      }
      nowFn = opts.now;
    }
    this._filePath = filePath;
    this._now = nowFn;
    this._proposals = new Map();
    this._tokens = new Map();
    if (fs.existsSync(this._filePath)) {
      const stat = fs.statSync(this._filePath);
      if (stat.isFile()) {
        const content = fs.readFileSync(this._filePath, "utf8");
        if (content.length > 0) {
          const lines = content.split("\n");
          for (const line of lines) {
            if (!line || line.trim().length === 0) {
              continue;
            }
            const ev = JSON.parse(line);
            this._applyEvent(ev);
          }
        }
      }
    }
  }

  /**
   * @returns {string}
   */
  _nowIso() {
    const v = this._now();
    if (typeof v === "string") {
      return v;
    }
    if (v instanceof Date) {
      return v.toISOString();
    }
    if (v && typeof v.toISOString === "function") {
      return v.toISOString();
    }
    return new Date(v).toISOString();
  }

  /**
   * @param {object} ev
   */
  _appendEvent(ev) {
    const dir = path.dirname(this._filePath);
    if (dir && dir !== "." && dir !== "") {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.appendFileSync(this._filePath, JSON.stringify(ev) + "\n", "utf8");
  }

  /**
   * @param {object} ev
   */
  _applyEvent(ev) {
    if (!ev || typeof ev !== "object") {
      return;
    }
    if (ev.type === "proposal_created") {
      let p = null;
      if (ev.proposal && typeof ev.proposal === "object") {
        p = ev.proposal;
      } else if (isNonEmptyString(ev.id)) {
        p = Object.assign({}, ev);
        delete p.type;
      }
      if (p && isNonEmptyString(p.id)) {
        this._proposals.set(p.id, deepCopy(p));
      }
      return;
    }
    if (ev.type === "proposal_decided") {
      const pid = ev.proposal_id;
      if (!isNonEmptyString(pid)) {
        return;
      }
      const prop = this._proposals.get(pid);
      if (!prop) {
        return;
      }
      const human = ev.human;
      const decision = ev.decision;
      const why = ev.why;
      const decided_at = ev.decided_at;
      prop.status = decision === "approve" ? "approved" : "rejected";
      prop.decision = {
        human: human,
        decision: decision,
        why: why,
        decided_at: decided_at,
      };
      if (decision === "approve") {
        const record = {
          proposal_id: pid,
          human: human,
          decision: decision,
          why: why,
          decided_at: decided_at,
        };
        let receipt_hash = ev.receipt_hash;
        if (!isNonEmptyString(receipt_hash)) {
          receipt_hash = crypto
            .createHash("sha256")
            .update(JSON.stringify(record), "utf8")
            .digest("hex");
        }
        let token_id = ev.token_id;
        if (!isNonEmptyString(token_id)) {
          token_id = "tok_" + String(receipt_hash).slice(0, 12);
        }
        const token = {
          token_id: token_id,
          proposal_id: pid,
          approved_by: human,
          why: why,
          fence: deepCopy(prop.fence),
          action: deepCopy(prop.action),
          issued_at: decided_at,
          receipt_hash: receipt_hash,
        };
        this._tokens.set(pid, token);
      }
      return;
    }
  }

  /**
   * @param {object} input
   * @returns {object}
   */
  createProposal(input) {
    if (!isPlainObject(input)) {
      fail("ERR_INVALID_PROPOSAL", "proposal input must be a plain object");
    }
    const agent_id = input.agent_id;
    const bound_human = input.bound_human;
    const action = input.action;
    const fence = input.fence;
    const justification = input.justification;
    if (!isNonEmptyString(agent_id)) {
      fail("ERR_INVALID_PROPOSAL", "agent_id must be a non-empty string");
    }
    if (!isNonEmptyString(bound_human)) {
      fail("ERR_INVALID_PROPOSAL", "bound_human must be a non-empty string");
    }
    if (!isPlainObject(action)) {
      fail("ERR_INVALID_PROPOSAL", "action must be a plain object");
    }
    if (!isNonEmptyString(action.kind)) {
      fail("ERR_INVALID_PROPOSAL", "action.kind must be a non-empty string");
    }
    if (!Array.isArray(action.subject_refs)) {
      fail("ERR_INVALID_PROPOSAL", "action.subject_refs must be an array");
    }
    for (const ref of action.subject_refs) {
      if (!isNonEmptyString(ref)) {
        fail(
          "ERR_INVALID_PROPOSAL",
          "action.subject_refs must be an array of non-empty strings"
        );
      }
    }
    if (!isPlainObject(fence)) {
      fail("ERR_INVALID_PROPOSAL", "fence must be a plain object");
    }
    const fields = ["from_department", "to_department", "from_tier", "to_tier"];
    for (const f of fields) {
      if (!isNonEmptyString(fence[f])) {
        fail("ERR_INVALID_PROPOSAL", "fence." + f + " must be a non-empty string");
      }
    }
    if (
      fence.from_department === fence.to_department &&
      fence.from_tier === fence.to_tier
    ) {
      fail(
        "ERR_NO_FENCE_CROSSED",
        "no fence crossed: the checkpoint only handles cross-fence actions"
      );
    }
    if (!isNonEmptyString(justification)) {
      fail("ERR_INVALID_PROPOSAL", "justification must be a non-empty string");
    }
    const id = "prop_" + crypto.randomBytes(6).toString("hex");
    const created_at = this._nowIso();
    const proposal = {
      id: id,
      agent_id: agent_id,
      bound_human: bound_human,
      action: {
        kind: action.kind,
        subject_refs: action.subject_refs.slice(),
      },
      fence: {
        from_department: fence.from_department,
        to_department: fence.to_department,
        from_tier: fence.from_tier,
        to_tier: fence.to_tier,
      },
      justification: justification,
      status: "pending",
      created_at: created_at,
    };
    const ev = {
      type: "proposal_created",
      proposal: deepCopy(proposal),
    };
    this._appendEvent(ev);
    this._proposals.set(id, deepCopy(proposal));
    return deepCopy(proposal);
  }

  /**
   * @param {string} proposalId
   * @param {object} input
   * @returns {{ proposal: object, status: string, token: object|null }}
   */
  decide(proposalId, input) {
    if (!isPlainObject(input)) {
      fail("ERR_INVALID_DECISION", "decision input must be a plain object");
    }
    const human = input.human;
    const decision = input.decision;
    const why = input.why;
    if (!isNonEmptyString(human)) {
      fail("ERR_INVALID_DECISION", "human must be a non-empty string");
    }
    if (decision !== "approve" && decision !== "reject") {
      fail("ERR_INVALID_DECISION", 'decision must be exactly "approve" or "reject"');
    }
    if (!isNonEmptyString(why)) {
      fail(
        "ERR_WHY_REQUIRED",
        "why is required: no decision is recorded without its reason"
      );
    }
    if (!isNonEmptyString(proposalId)) {
      fail("ERR_UNKNOWN_PROPOSAL", "unknown proposal: " + String(proposalId));
    }
    const prop = this._proposals.get(proposalId);
    if (!prop) {
      fail("ERR_UNKNOWN_PROPOSAL", "unknown proposal: " + proposalId);
    }
    if (prop.status !== "pending") {
      fail(
        "ERR_ALREADY_DECIDED",
        "proposal already decided: a decision is final"
      );
    }
    if (human === prop.bound_human) {
      fail(
        "ERR_SELF_APPROVAL",
        "self-approval is not allowed: the person whose agent is asking cannot decide their own proposal"
      );
    }
    const decided_at = this._nowIso();
    if (decision === "approve") {
      const record = {
        proposal_id: proposalId,
        human: human,
        decision: decision,
        why: why,
        decided_at: decided_at,
      };
      const receipt_hash = crypto
        .createHash("sha256")
        .update(JSON.stringify(record), "utf8")
        .digest("hex");
      const token_id = "tok_" + crypto.randomBytes(6).toString("hex");
      const token = {
        token_id: token_id,
        proposal_id: proposalId,
        approved_by: human,
        why: why,
        fence: deepCopy(prop.fence),
        action: deepCopy(prop.action),
        issued_at: decided_at,
        receipt_hash: receipt_hash,
      };
      const ev = {
        type: "proposal_decided",
        proposal_id: proposalId,
        human: human,
        decision: decision,
        why: why,
        decided_at: decided_at,
        token_id: token_id,
        receipt_hash: receipt_hash,
      };
      this._appendEvent(ev);
      prop.status = "approved";
      prop.decision = {
        human: human,
        decision: decision,
        why: why,
        decided_at: decided_at,
      };
      this._tokens.set(proposalId, deepCopy(token));
      return {
        proposal: deepCopy(prop),
        status: "approved",
        token: deepCopy(token),
      };
    }
    const ev = {
      type: "proposal_decided",
      proposal_id: proposalId,
      human: human,
      decision: decision,
      why: why,
      decided_at: decided_at,
    };
    this._appendEvent(ev);
    prop.status = "rejected";
    prop.decision = {
      human: human,
      decision: decision,
      why: why,
      decided_at: decided_at,
    };
    return {
      proposal: deepCopy(prop),
      status: "rejected",
      token: null,
    };
  }

  /**
   * @param {string} proposalId
   * @returns {object}
   */
  getExecutableToken(proposalId) {
    const prop = this._proposals.get(proposalId);
    if (!prop) {
      return { refused: true, reason: "unknown_proposal" };
    }
    if (prop.status === "pending") {
      return { refused: true, reason: "pending" };
    }
    if (prop.status === "rejected") {
      return { refused: true, reason: "rejected" };
    }
    const stored = this._tokens.get(proposalId);
    if (stored) {
      return deepCopy(stored);
    }
    const d = prop.decision;
    const record = {
      proposal_id: proposalId,
      human: d.human,
      decision: d.decision,
      why: d.why,
      decided_at: d.decided_at,
    };
    const receipt_hash = crypto
      .createHash("sha256")
      .update(JSON.stringify(record), "utf8")
      .digest("hex");
    const token = {
      token_id: "tok_" + String(receipt_hash).slice(0, 12),
      proposal_id: proposalId,
      approved_by: d.human,
      why: d.why,
      fence: deepCopy(prop.fence),
      action: deepCopy(prop.action),
      issued_at: d.decided_at,
      receipt_hash: receipt_hash,
    };
    return deepCopy(token);
  }

  /**
   * @param {string} proposalId
   * @returns {object|null}
   */
  getProposal(proposalId) {
    const prop = this._proposals.get(proposalId);
    if (!prop) {
      return null;
    }
    return deepCopy(prop);
  }

  /**
   * @returns {object[]}
   */
  listProposals() {
    return Array.from(this._proposals.values()).map((p) => deepCopy(p));
  }
}

module.exports = { ProposalStore };
