"use strict";
/**
 * signals.js — append-only, content-free signal log ("the road") for an agent federation.
 *
 * Think of this module as road infrastructure, not cargo. Departments run their
 * own agents, but they all share one road: a flat file of signals that says who
 * moved, when, and what it points at — never what was said.
 *
 * Doctrine:
 * - Metadata only. Signals carry references (hashes/ids), never content. If you
 *   need to move content, store it elsewhere and put only its ref here.
 * - Append-only. Writers only ever append one JSON line. There is no update,
 *   delete, or rewrite path in this module by design.
 * - Hash-chained. Every record commits to the previous record's hash. Any later
 *   edit, deletion, or reorder breaks the chain and `verify()` will find it.
 * - Crash-recoverable. The log is the source of truth on disk; a new instance
 *   recovers `prev_hash` and `seq` from the last line and keeps going.
 * - Fail loud. Bad signals throw with `err.code = 'ERR_INVALID_SIGNAL'`.
 *   Corrupt history never verifies silently.
 */
const crypto = require('node:crypto');
const fs = require('node:fs');

const GENESIS = "0".repeat(64);

const ALLOWED_FIELDS = ["ts", "agent_id", "bound_human", "department", "tier", "kind", "subject_refs"];
const FORBIDDEN_CONTENT_FIELDS = ["content", "body", "text"];
const STRING_FIELDS = ["agent_id", "bound_human", "department", "tier", "kind"];

function validationError(message) {
  const err = new Error(message);
  err.code = "ERR_INVALID_SIGNAL";
  return err;
}

function isPlainObject(value) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

function validateSignal(signal) {
  if (!isPlainObject(signal)) {
    throw validationError("invalid signal: signal must be a plain object");
  }

  for (const field of FORBIDDEN_CONTENT_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(signal, field)) {
      throw validationError(
        'signals are content-free metadata: field "' + field + '" is forbidden and must not be present'
      );
    }
  }

  for (const key of Object.keys(signal)) {
    if (ALLOWED_FIELDS.indexOf(key) === -1) {
      throw validationError(
        'unknown field "' + key + '": only ' + ALLOWED_FIELDS.join(", ") + " are permitted"
      );
    }
  }

  for (const field of ALLOWED_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(signal, field)) {
      throw validationError('missing required field "' + field + '"');
    }
  }

  if (typeof signal.ts !== "string" || Number.isNaN(Date.parse(signal.ts))) {
    throw validationError('invalid "ts": must be an ISO-8601 timestamp string that parses as a valid date');
  }

  for (const field of STRING_FIELDS) {
    if (typeof signal[field] !== "string" || signal[field].length === 0) {
      throw validationError('invalid "' + field + '": must be a non-empty string');
    }
  }

  if (!Array.isArray(signal.subject_refs)) {
    throw validationError('invalid "subject_refs": must be an array');
  }
  for (let i = 0; i < signal.subject_refs.length; i++) {
    const v = signal.subject_refs[i];
    if (typeof v !== "string" || v.length === 0) {
      throw validationError('invalid "subject_refs[' + i + ']": must be a non-empty string');
    }
  }

  return true;
}

class SignalLog {
  constructor(filePath) {
    if (typeof filePath !== "string" || filePath.length === 0) {
      throw new Error("SignalLog requires a non-empty filePath string");
    }
    this.filePath = filePath;
    this._prevHash = GENESIS;
    this._nextSeq = 0;

    let exists = false;
    try {
      exists = fs.existsSync(filePath);
    } catch (_e) {
      exists = false;
    }

    if (!exists) {
      return;
    }

    const data = fs.readFileSync(filePath, "utf8");
    if (data.length === 0 || data.trim().length === 0) {
      return;
    }

    const lines = data.split("\n");
    let lastLine = "";
    for (let i = lines.length - 1; i >= 0; i--) {
      if (lines[i].trim().length !== 0) {
        lastLine = lines[i];
        break;
      }
    }
    if (lastLine.length === 0) {
      return;
    }

    let last;
    try {
      last = JSON.parse(lastLine);
    } catch (_e) {
      throw new Error("signal log is corrupted: last line is not valid JSON");
    }
    if (!last || typeof last.hash !== "string" || typeof last.seq !== "number") {
      throw new Error("signal log is corrupted: last record missing hash or seq");
    }
    this._prevHash = last.hash;
    this._nextSeq = last.seq + 1;
  }

  append(signal) {
    validateSignal(signal);
    const seq = this._nextSeq;
    const prevHash = this._prevHash;
    const core = {
      seq: seq,
      ts: signal.ts,
      agent_id: signal.agent_id,
      bound_human: signal.bound_human,
      department: signal.department,
      tier: signal.tier,
      kind: signal.kind,
      subject_refs: signal.subject_refs.slice()
    };
    const hash = crypto.createHash("sha256").update(prevHash + JSON.stringify(core), "utf8").digest("hex");
    const record = {
      seq: core.seq,
      ts: core.ts,
      agent_id: core.agent_id,
      bound_human: core.bound_human,
      department: core.department,
      tier: core.tier,
      kind: core.kind,
      subject_refs: core.subject_refs,
      prev_hash: prevHash,
      hash: hash
    };
    fs.appendFileSync(this.filePath, JSON.stringify(record) + "\n", "utf8");
    this._prevHash = hash;
    this._nextSeq = seq + 1;
    return record;
  }

  readAll() {
    let exists = false;
    try {
      exists = fs.existsSync(this.filePath);
    } catch (_e) {
      exists = false;
    }
    if (!exists) {
      return [];
    }
    const data = fs.readFileSync(this.filePath, "utf8");
    if (data.length === 0 || data.trim().length === 0) {
      return [];
    }
    const out = [];
    const lines = data.split("\n");
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.trim().length === 0) {
        continue;
      }
      let obj;
      try {
        obj = JSON.parse(line);
      } catch (_e) {
        throw new Error("signal log is corrupted: invalid JSON on line " + (i + 1));
      }
      out.push(obj);
    }
    return out;
  }

  verify() {
    let exists = false;
    try {
      exists = fs.existsSync(this.filePath);
    } catch (_e) {
      exists = false;
    }
    if (!exists) {
      return { ok: true, count: 0 };
    }
    const data = fs.readFileSync(this.filePath, "utf8");
    if (data.length === 0 || data.trim().length === 0) {
      return { ok: true, count: 0 };
    }
    const rawLines = data.split("\n");
    const records = [];
    for (let i = 0; i < rawLines.length; i++) {
      const line = rawLines[i];
      if (line.trim().length === 0) {
        continue;
      }
      try {
        records.push(JSON.parse(line));
      } catch (_e) {
        return { ok: false, brokenAt: records.length, reason: "invalid JSON at line " + (i + 1) };
      }
    }

    let prev = GENESIS;
    for (let i = 0; i < records.length; i++) {
      const rec = records[i];
      const seqForReport = rec !== null && typeof rec === "object" && typeof rec.seq === "number" ? rec.seq : i;
      if (rec === null || typeof rec !== "object" || Array.isArray(rec) || typeof rec.seq !== "number" || rec.seq !== i) {
        const got = rec !== null && typeof rec === "object" && !Array.isArray(rec) ? String(rec.seq) : "missing";
        return { ok: false, brokenAt: seqForReport, reason: "bad seq at index " + i + ": expected " + i + " but got " + got };
      }
      if (rec.prev_hash !== prev) {
        return { ok: false, brokenAt: rec.seq, reason: "prev_hash mismatch at seq " + rec.seq + ": expected " + prev + " but got " + rec.prev_hash };
      }
      const core = {
        seq: rec.seq,
        ts: rec.ts,
        agent_id: rec.agent_id,
        bound_human: rec.bound_human,
        department: rec.department,
        tier: rec.tier,
        kind: rec.kind,
        subject_refs: rec.subject_refs
      };
      const expected = crypto.createHash("sha256").update(String(rec.prev_hash) + JSON.stringify(core), "utf8").digest("hex");
      if (rec.hash !== expected) {
        return { ok: false, brokenAt: rec.seq, reason: "hash mismatch at seq " + rec.seq + ": expected " + expected + " but got " + rec.hash };
      }
      prev = rec.hash;
    }
    return { ok: true, count: records.length };
  }
}

function verifyFile(filePath) {
  const log = new SignalLog(filePath);
  return log.verify();
}

module.exports = { GENESIS, validateSignal, SignalLog, verifyFile };
