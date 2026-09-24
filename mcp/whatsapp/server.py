"""WhatsApp MCP server — STUB.

Exposes send_message / read_messages as MCP tools so agents can be built and
tested against a stable contract NOW. The bodies return clearly-marked stub
payloads; real WhatsApp Business Cloud API wiring replaces the bodies later
(TODOs inline). Nothing here sends a real message.

Run:  python mcp/whatsapp/server.py   (stdio transport, for MCP clients)
Test: pytest evals/test_tools.py      (imports the plain functions below)
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("whatsapp-stub")


def send_message(to: str, body: str) -> dict:
    """STUB: queue an outbound WhatsApp message.

    TODO (real wiring): POST to WhatsApp Business Cloud API
    /<PHONE_NUMBER_ID>/messages with the template or free-form body;
    requires WHATSAPP_TOKEN + PHONE_NUMBER_ID env. Respect the Oct 1 2026
    per-message pricing — batch and stay in-window (see COSTS.md).
    """
    return {
        "status": "stub",
        "to": to,
        "body": body,
        "note": "no real message sent — wire WHATSAPP_TOKEN to go live",
    }


def read_messages(conversation_id: str, limit: int = 20) -> dict:
    """STUB: fetch recent messages for a conversation.

    TODO (real wiring): GET from the WhatsApp Business Cloud API conversation
    endpoint; requires WHATSAPP_TOKEN env. Paginate for limit > 20.
    """
    return {
        "status": "stub",
        "conversation_id": conversation_id,
        "messages": [],
        "note": "no real fetch performed — wire WHATSAPP_TOKEN to go live",
    }


mcp.tool()(send_message)
mcp.tool()(read_messages)


if __name__ == "__main__":
    mcp.run()
