"""M-Pesa (Daraja) MCP server — STUB.

Exposes get_balance / stk_push as MCP tools against a stable contract NOW.
Bodies return clearly-marked stub payloads; Daraja sandbox wiring replaces them
later (TODOs inline). Nothing here touches money.

Run:  python mcp/mpesa/server.py   (stdio transport, for MCP clients)
Test: pytest evals/test_tools.py   (imports the plain functions below)

HITL: stk_push moves real money when wired — it MUST go through
policy/approvals.py before execution. The stub does not enforce this; the
wiring phase must.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mpesa-stub")


def get_balance(account: str) -> dict:
    """STUB: query account balance.

    TODO (real wiring): Daraja sandbox — OAuth token via consumer key/secret,
    then Account Balance API. Requires DARAJA_CONSUMER_KEY/SECRET env.
    Start against the sandbox URLs, never production, until evals pass.
    """
    return {
        "status": "stub",
        "account": account,
        "balance": None,
        "note": "no real query performed — wire Daraja sandbox to go live",
    }


def stk_push(phone: str, amount_kes: int, reference: str) -> dict:
    """STUB: initiate an M-Pesa STK push.

    TODO (real wiring): Daraja STK Push API against the sandbox first.
    HITL REQUIRED: real wiring must call policy.request_approval() before
    executing — money movement is never agent-autonomous.
    """
    return {
        "status": "stub",
        "phone": phone,
        "amount_kes": amount_kes,
        "reference": reference,
        "note": "no real push performed — wire Daraja sandbox + HITL to go live",
    }


mcp.tool()(get_balance)
mcp.tool()(stk_push)


if __name__ == "__main__":
    mcp.run()
