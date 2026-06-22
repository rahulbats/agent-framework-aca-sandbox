"""FastAPI entry point.

Each chat session gets:
  * its own agent conversation thread (multi-turn memory), and
  * its own isolated sandbox (via SandboxSessionManager).

State is kept in-process for sample simplicity. For multi-replica production use,
back the thread/session store with a shared store (e.g. Redis or Cosmos DB) and
run a single replica per session or use sticky routing.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import build_agent, current_session_id
from .sandbox import SandboxSessionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str


class AppState:
    def __init__(self) -> None:
        self.sandbox_manager = SandboxSessionManager()
        self.agent = build_agent(self.sandbox_manager)
        # session_id -> agent conversation session (carries chat history)
        self.sessions: dict[str, object] = {}
        self._lock = asyncio.Lock()

    async def get_session(self, session_id: str):
        async with self._lock:
            session = self.sessions.get(session_id)
            if session is None:
                session = self.agent.create_session(session_id=session_id)
                self.sessions[session_id] = session
            return session

    async def reset(self, session_id: str) -> bool:
        async with self._lock:
            had_session = self.sessions.pop(session_id, None) is not None
        had_sandbox = await self.sandbox_manager.reset(session_id)
        return had_session or had_sandbox


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.app_state = AppState()
    logger.info("Agent and sandbox manager initialized.")
    try:
        yield
    finally:
        await app.state.app_state.sandbox_manager.shutdown()
        logger.info("Sandboxes torn down.")


app = FastAPI(title="Agent Framework + ACA Sandbox", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    state: AppState = app.state.app_state
    session_id = req.session_id or uuid.uuid4().hex

    session = await state.get_session(session_id)

    # Bind the session id so the run_python tool targets this session's sandbox.
    token = current_session_id.set(session_id)
    try:
        result = await state.agent.run(req.message, session=session)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent run failed for session %s", session_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        current_session_id.reset(token)

    return ChatResponse(session_id=session_id, reply=str(result))


@app.post("/api/sessions/{session_id}/reset")
async def reset_session(session_id: str) -> dict[str, bool]:
    state: AppState = app.state.app_state
    existed = await state.reset(session_id)
    return {"reset": existed}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
