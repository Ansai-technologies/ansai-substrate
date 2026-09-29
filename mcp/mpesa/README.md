# M-Pesa (Daraja) MCP server

**Status: live on sandbox when keys are set, stub otherwise.** The tool
contract (`get_balance`, `stk_push`) is stable and pinned by
`evals/test_tools.py`. With no `DARAJA_CONSUMER_KEY`/`DARAJA_CONSUMER_SECRET`
in the environment, both tools return the original stub payloads and touch no
network. With keys set, `stk_push` performs a real Daraja **sandbox** STK
push — after a human approves it.

There is deliberately **no production switch** in v1: the base URL is a
constant in `server.py`. Talking to production is a separate, reviewed change.

## Going live on sandbox

1. Register at [developer.safaricom.co.ke](https://developer.safaricom.co.ke),
   create a sandbox app, map **Lipa Na M-Pesa Sandbox** (+ **M-Pesa Sandbox**
   for later B2C work, **B2C Hakikisha Sandbox** for name verification).
2. Copy from the app page: **Consumer Key**, **Consumer Secret**.
   From Test Credentials: **Passkey** (sandbox shortcode is `174379`).
3. Put them in your environment (never commit them):
   ```bash
   export DARAJA_CONSUMER_KEY="..."
   export DARAJA_CONSUMER_SECRET="..."
   export DARAJA_PASSKEY="..."
   # optional:
   export DARAJA_SHORTCODE="174379"
   export DARAJA_CALLBACK_URL="https://<your-public-url>/daraja/callback"
   ```
4. Trigger `stk_push`. A HITL approval request appears
   (`policy/approve.py approve|deny <id>`); approve it, and the sandbox STK
   push goes out. Test numbers: `254708374149` succeeds, `254708374150`
   simulates insufficient funds, `254708374151` times out.

## Safety rules (policy, not suggestions)

- **HITL is mandatory for `stk_push`.** `server.py` calls
  `policy.request_approval()` before any HTTP; denied/timed-out approvals
  return `{"status": "denied"}` and no request is sent.
- Money movement is never agent-autonomous. See `policy/approvals.py`.
- Sandbox only. Real money needs the go-live change + fresh review.

## Phase 0b (not yet)

- `get_balance`: needs `DARAJA_SECURITY_CREDENTIAL` (RSA-encrypted initiator
  password using Safaricom's cert) plus public `ResultURL`/`QueueTimeOutURL`.
  Returns a plain error until wired — it never fakes a number.
- `b2c_payment` (B2C payouts, e.g. sending money to mum): same credential
  requirement. Tool to be added with the wiring.
- `hakikisha` (B2C name verification): verify recipient name before money
  moves — the trust primitive for Tuma.
