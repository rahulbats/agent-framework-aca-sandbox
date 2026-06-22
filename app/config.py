"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Agent Framework does not auto-load .env files; do it here for local dev.
load_dotenv()

# An empty AZURE_OPENAI_API_KEY (e.g. the blank line in .env) is otherwise read by
# the Agent Framework as a real-but-empty key, which overrides managed-identity auth
# and breaks the client. Strip it so credential-based auth works.
if not os.environ.get("AZURE_OPENAI_API_KEY"):
    os.environ.pop("AZURE_OPENAI_API_KEY", None)


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable '{name}' is not set.")
    return value


@dataclass(frozen=True)
class Settings:
    # Azure OpenAI
    aoai_endpoint: str
    aoai_deployment: str
    aoai_api_version: str
    aoai_api_key: str | None

    # ACA Sandbox
    subscription_id: str
    resource_group: str
    sandbox_group: str
    region: str

    # Sandbox tuning
    sandbox_disk: str
    sandbox_cpu: str
    sandbox_memory: str
    sandbox_auto_suspend_seconds: int

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            aoai_endpoint=_require("AZURE_OPENAI_ENDPOINT"),
            aoai_deployment=_require("AZURE_OPENAI_DEPLOYMENT"),
            aoai_api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            aoai_api_key=os.environ.get("AZURE_OPENAI_API_KEY") or None,
            subscription_id=_require("AZURE_SUBSCRIPTION_ID"),
            resource_group=_require("AZURE_RESOURCE_GROUP"),
            sandbox_group=_require("AZURE_SANDBOX_GROUP"),
            region=os.environ.get("AZURE_REGION", "eastus2"),
            sandbox_disk=os.environ.get("SANDBOX_DISK", "ubuntu"),
            sandbox_cpu=os.environ.get("SANDBOX_CPU", "1000m"),
            sandbox_memory=os.environ.get("SANDBOX_MEMORY", "2048Mi"),
            sandbox_auto_suspend_seconds=int(
                os.environ.get("SANDBOX_AUTO_SUSPEND_SECONDS", "300")
            ),
        )


settings = Settings.load()
