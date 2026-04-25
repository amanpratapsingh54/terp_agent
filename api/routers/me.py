"""/me — profile, preferences, commitments."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from api import store
from api.models import OK

router = APIRouter(prefix="/me", tags=["profile"])


def _get_student(sid: str = "stu_001") -> dict:
    s = store.find_one("students", sid)
    if not s:
        raise HTTPException(404, f"student {sid} not found")
    return s


@router.get("", operation_id="get_profile", summary="Get the current student profile")
def get_me(student_id: str = "stu_001") -> dict:
    return _get_student(student_id)


@router.patch("", operation_id="patch_profile", summary="Update profile fields")
def patch_me(patch: dict[str, Any], student_id: str = "stu_001") -> dict:
    updated = store.update_one("students", student_id, patch)
    if not updated:
        raise HTTPException(404, "student not found")
    return updated


@router.post("/interests", operation_id="add_interests", summary="Append interests")
def add_interests(interests: list[str], student_id: str = "stu_001") -> dict:
    s = _get_student(student_id)
    existing = set(s.get("interests", []))
    existing.update(interests)
    return store.update_one("students", student_id, {"interests": sorted(existing)}) or {}


@router.get("/commitments", operation_id="list_commitments",
            summary="Saved events, booked rooms, tracked scholarships, applied jobs")
def commitments(student_id: str = "stu_001") -> dict:
    s = _get_student(student_id)
    return s.get("saved", {})
