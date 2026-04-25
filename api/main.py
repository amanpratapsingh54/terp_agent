"""TerpAgent — Unified Campus API for University of Maryland.

This FastAPI app is consumed by the TerpAgent Claude Cowork skill. It exposes a
single OpenAPI surface that fans out to Canvas, Terplink, Handshake, UMD HR,
OSFA, ResLife, UMD Libraries, Testudo, and assorted professor pages.

In this dummy build every router reads from seed JSON under /data. Swap the
router bodies for real HTTP calls to go live.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routers import (
    agent,
    canvas,
    handshake,
    housing,
    jobs,
    library,
    me,
    professors,
    scholarships,
    social,
    terplink,
    travel,
)

app = FastAPI(
    title="TerpAgent — Unified Campus API",
    version="0.1.0",
    description=(
        "One OpenAPI surface over every UMD service a student touches. "
        "Designed to be ingested by a Claude Cowork agent (see CLAUDE_COWORK_PROMPT.md)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(me.router)
app.include_router(canvas.router)
app.include_router(terplink.router)
app.include_router(handshake.router)
app.include_router(jobs.router)
app.include_router(scholarships.router)
app.include_router(housing.router)
app.include_router(library.router)
app.include_router(social.router)
app.include_router(professors.router)
app.include_router(travel.router)
app.include_router(agent.router)

# --- UI ----------------------------------------------------------------
UI_DIR = Path(__file__).parent.parent / "ui"
if UI_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(UI_DIR), html=True), name="ui")


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "service": "TerpAgent Unified Campus API",
        "university": "University of Maryland, College Park",
        "ui": "/app",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"ok": True}
