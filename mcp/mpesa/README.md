# M-Pesa (Daraja) MCP server — STUB

**Status: stub.** Contract (`get_balance`, `stk_push`) is stable and tested;
bodies return marked stub payloads. Nothing touches money.

## Going live (later phase)

1. Register on the Daraja portal, get sandbox consumer key/secret.
2. Replace the bodies in `server.py` per the inline TODOs — **sandbox URLs
   first**, production only after evals pass on sandbox traffic.
3. **HITL is mandatory for `stk_push`**: the wiring phase must call
   `policy.request_approval()` before executing. Money movement is never
   agent-autonomous — this is policy, not a suggestion (see policy/approvals.py).
