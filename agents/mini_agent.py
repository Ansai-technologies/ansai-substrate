"""Mini agent: the per-person / per-role worker.

Talks ONLY to the gateway (OpenAI-compatible /v1). It never sees provider keys
and never calls a provider directly — the model group name (default `workhorse`)
is resolved by LiteLLM, which also owns failover and spend caps.

Requires: gateway running (see gateway/README.md).
"""

import os

from agno.agent import Agent
from agno.models.openai import OpenAIChat  # OpenAI-compatible; base_url -> gateway

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4000")
# Agents authenticate to the gateway with a group virtual key in production;
# the master key default below is local-dev only.
GATEWAY_API_KEY = os.environ.get(
    "GATEWAY_API_KEY",
    os.environ.get("LITELLM_MASTER_KEY", "sk-ansai-dev-local"),
)
MODEL_GROUP = os.environ.get("MINI_MODEL", "workhorse")


def build_mini_agent(name: str, instructions: str, tools: list | None = None) -> Agent:
    """Construct a worker agent bound to the gateway's model group."""
    return Agent(
        name=name,
        model=OpenAIChat(
            id=MODEL_GROUP,  # LiteLLM model_name, e.g. "workhorse"
            base_url=f"{GATEWAY_URL}/v1",
            api_key=GATEWAY_API_KEY,
        ),
        instructions=instructions,
        tools=tools or [],
        markdown=False,  # structured output stays parseable
    )


def run_task(agent: Agent, task: str) -> str:
    """Run one task, return the text response."""
    response = agent.run(task)
    return response.content or ""
