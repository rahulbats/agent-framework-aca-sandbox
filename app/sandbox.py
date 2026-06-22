"""Per-session sandbox manager.

Gives every chat session its own isolated Linux sandbox, mirroring how Microsoft
Foundry isolates code-interpreter execution per thread. Each session_id maps to a
dedicated ACA Sandbox; code from one session can never touch another session's
filesystem, processes, or network namespace.

The ACA Sandbox SDK is synchronous, so blocking calls are offloaded to worker
threads with ``asyncio.to_thread`` to keep the FastAPI event loop responsive.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from azure.containerapps.sandbox import SandboxGroupClient, endpoint_for_region
from azure.identity import DefaultAzureCredential

from .config import settings

logger = logging.getLogger(__name__)

# Heredoc delimiter that is unlikely to appear in user/agent generated code.
_PY_HEREDOC = "AF_SANDBOX_PYEOF"


@dataclass
class SandboxSession:
    """Tracks a single session's sandbox handle and last-used time."""

    session_id: str
    sandbox: Any
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


class SandboxSessionManager:
    """Creates, reuses, and tears down one sandbox per session id."""

    def __init__(self) -> None:
        self._credential = DefaultAzureCredential()
        self._client = SandboxGroupClient(
            endpoint_for_region(settings.region),
            self._credential,
            subscription_id=settings.subscription_id,
            resource_group=settings.resource_group,
            sandbox_group=settings.sandbox_group,
        )
        self._sessions: dict[str, SandboxSession] = {}
        # Guards the _sessions map; a per-session lock prevents two concurrent
        # requests for the same session from each creating a sandbox.
        self._map_lock = asyncio.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def _lock_for(self, session_id: str) -> asyncio.Lock:
        async with self._map_lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[session_id] = lock
            return lock

    async def get_or_create(self, session_id: str) -> SandboxSession:
        """Return the session's sandbox, creating one on first use."""
        lock = await self._lock_for(session_id)
        async with lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_used = time.time()
                return session

            logger.info("Creating sandbox for session %s", session_id)
            sandbox = await asyncio.to_thread(self._create_sandbox, session_id)
            session = SandboxSession(session_id=session_id, sandbox=sandbox)
            self._sessions[session_id] = session
            return session

    def _create_sandbox(self, session_id: str) -> Any:
        """Synchronous sandbox creation (runs in a worker thread)."""
        poller = self._client.begin_create_sandbox(
            disk=settings.sandbox_disk,
            cpu=settings.sandbox_cpu,
            memory=settings.sandbox_memory,
            auto_suspend_seconds=settings.sandbox_auto_suspend_seconds,
            labels={"session": session_id, "app": "agent-framework-sample"},
        )
        return poller.result()

    async def run_python(self, session_id: str, code: str) -> str:
        """Execute Python code inside the session's isolated sandbox."""
        session = await self.get_or_create(session_id)
        session.last_used = time.time()
        return await asyncio.to_thread(self._exec_python, session.sandbox, code)

    @staticmethod
    def _exec_python(sandbox: Any, code: str) -> str:
        """Run code via a stdin heredoc so arbitrary source is passed safely."""
        command = f"python3 - <<'{_PY_HEREDOC}'\n{code}\n{_PY_HEREDOC}"
        result = sandbox.exec(command)

        stdout = (getattr(result, "stdout", "") or "").strip()
        stderr = (getattr(result, "stderr", "") or "").strip()
        exit_code = getattr(result, "exit_code", None)

        parts: list[str] = []
        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(f"[stderr]\n{stderr}")
        if exit_code not in (None, 0):
            parts.append(f"[exit code: {exit_code}]")
        return "\n".join(parts) if parts else "(no output)"

    async def reset(self, session_id: str) -> bool:
        """Delete the session's sandbox and forget it. Returns True if one existed."""
        lock = await self._lock_for(session_id)
        async with lock:
            session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        logger.info("Deleting sandbox for session %s", session_id)
        await asyncio.to_thread(self._safe_delete, session.sandbox)
        return True

    @staticmethod
    def _safe_delete(sandbox: Any) -> None:
        try:
            sandbox.delete()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            logger.exception("Failed to delete sandbox")

    async def shutdown(self) -> None:
        """Tear down all sandboxes (called on app shutdown)."""
        async with self._map_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            await asyncio.to_thread(self._safe_delete, session.sandbox)
