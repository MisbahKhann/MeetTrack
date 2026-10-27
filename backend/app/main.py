"""MeetTrack backend entry point.

Mounts all API routers under /api/v1.
Start with: uvicorn app.main:app --reload  (run from backend/)
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agent.llm import LLMError
from app.agent.orchestrator import CycleError
from app.api import actions, exports, meetings, proposals, teams
from app.tools.action_store import (
    DuplicateFileError,
    InvalidStateError,
    NotFoundError,
    ValidationError,
)

app = FastAPI(
    title="MeetTrack",
    description="Agentic action-tracking system for FYP teams.",
    version="0.1.0",
)


# Exception handlers for clean error responses without tracebacks
@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(InvalidStateError)
async def invalid_state_handler(request: Request, exc: InvalidStateError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(DuplicateFileError)
async def duplicate_file_handler(request: Request, exc: DuplicateFileError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(CycleError)
async def cycle_error_handler(request: Request, exc: CycleError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


# Routers
app.include_router(teams.router, prefix="/api/v1")
app.include_router(meetings.router, prefix="/api/v1")
app.include_router(proposals.router, prefix="/api/v1")
app.include_router(actions.router, prefix="/api/v1")
app.include_router(exports.router, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness probe. Returns service name and version."""
    return {"status": "ok", "service": "meettrack-backend", "version": "0.1.0"}
