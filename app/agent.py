"""Builds the Microsoft Agent Framework agent.

The agent exposes a single ``run_python`` tool that executes code inside the
caller's isolated sandbox. The active session id is carried in a ContextVar so
the tool always targets the right sandbox without threading the id through the
model's tool-call arguments.
"""
from __future__ import annotations

import contextvars
from typing import Annotated

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from azure.identity.aio import DefaultAzureCredential
from pydantic import Field

from .config import settings
from .sandbox import SandboxSessionManager

# Set per-request so the tool knows which session's sandbox to use.
current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_session_id"
)

_AGENT_INSTRUCTIONS = (
    "You are a helpful data and coding assistant. "
    "When a task requires computation, data analysis, file manipulation, or "
    "running code, use the run_python tool. Code runs in a secure, isolated "
    "Linux sandbox that is private to this conversation and persists between "
    "your tool calls within the session, so you can build up state across "
    "steps. Always print results you want to keep. Summarize tool output for "
    "the user in clear language."
)


def build_agent(sandbox_manager: SandboxSessionManager) -> Agent:
    """Create the chat agent wired to the sandbox-backed code interpreter."""

    async def run_python(
        code: Annotated[
            str,
            Field(
                description=(
                    "Python 3 source code to execute in the session's isolated "
                    "sandbox. Print anything you need to read back."
                )
            ),
        ],
    ) -> str:
        """Execute Python code in this conversation's private sandbox and return stdout/stderr."""
        session_id = current_session_id.get()
        return await sandbox_manager.run_python(session_id, code)

    return Agent(
        client=_build_chat_client(),
        name="SandboxAgent",
        instructions=_AGENT_INSTRUCTIONS,
        tools=[run_python],
    )


def _build_chat_client() -> OpenAIChatClient:
    """Route to Azure OpenAI. Use an API key if provided, else managed identity."""
    if settings.aoai_api_key:
        # Passing azure_endpoint forces Azure routing even with a key.
        return OpenAIChatClient(
            model=settings.aoai_deployment,
            azure_endpoint=settings.aoai_endpoint,
            api_version=settings.aoai_api_version,
            api_key=settings.aoai_api_key,
        )

    return OpenAIChatClient(
        model=settings.aoai_deployment,
        azure_endpoint=settings.aoai_endpoint,
        api_version=settings.aoai_api_version,
        credential=DefaultAzureCredential(),
    )
