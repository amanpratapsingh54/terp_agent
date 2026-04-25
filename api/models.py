"""Shared Pydantic models for the TerpAgent API.

Ranking endpoints return a consistent envelope so the Claude agent can always
parse `score`, `why`, and `blockers` without per-service branching.
"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class MatchEnvelope(BaseModel, Generic[T]):
    item: T
    score: float  # 0.0 - 1.0
    why: list[str]  # human-readable reasons, used directly by the LLM
    blockers: list[str] = []  # soft conflicts like "overlaps with CMSC 414"


class MatchRequest(BaseModel):
    student_id: str = "stu_001"
    interests: list[str] | None = None
    free_slots: list[str] | None = None  # ISO date ranges
    friends: list[str] | None = None
    limit: int = 5
    extra: dict[str, Any] | None = None


class Action(BaseModel):
    student_id: str = "stu_001"
    id: str  # id of the thing being acted upon


class OK(BaseModel):
    ok: bool = True
    message: str | None = None
