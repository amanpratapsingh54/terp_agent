"""/canvas — courses, assignments, deadlines, grades, announcements.

TODO real integration: wrap Canvas LMS REST API. UMD endpoint is
https://umd.instructure.com/api/v1 and uses OAuth2. Each student passes a
personal access token via Authorization: Bearer.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from api import store

router = APIRouter(prefix="/canvas", tags=["canvas"])


def _student_courses(student_id: str) -> list[dict]:
    return [c for c in store.get("canvas_courses") if student_id in c.get("student_ids", [])]


@router.get("/courses", operation_id="list_courses",
            summary="Current enrollments")
def list_courses(student_id: str = "stu_001") -> list[dict]:
    return _student_courses(student_id)


@router.get("/courses/{course_id}", operation_id="get_course")
def get_course(course_id: str) -> dict:
    c = store.find_one("canvas_courses", course_id)
    if not c:
        raise HTTPException(404, "course not found")
    return c


@router.get("/courses/{course_id}/syllabus", operation_id="get_syllabus")
def get_syllabus(course_id: str) -> dict:
    c = store.find_one("canvas_courses", course_id)
    if not c:
        raise HTTPException(404, "course not found")
    return {
        "course_id": course_id,
        "text": (
            f"Syllabus for {c['code']} {c['title']}. Late policy: 10% per day up to 3 days. "
            "Academic integrity: all work must be your own. See course page for details."
        ),
    }


@router.get("/assignments", operation_id="list_assignments",
            summary="Upcoming assignments across courses, optionally filtered by due window")
def list_assignments(
    student_id: str = "stu_001",
    course_id: str | None = None,
    due_within: str | None = Query(None, description="e.g. 3d, 7d, 24h"),
    only_unsubmitted: bool = True,
) -> list[dict]:
    cutoff = None
    if due_within:
        unit = due_within[-1]
        n = int(due_within[:-1])
        delta = timedelta(days=n) if unit == "d" else timedelta(hours=n)
        cutoff = datetime.now(timezone.utc) + delta

    out: list[dict] = []
    for c in _student_courses(student_id):
        if course_id and c["id"] != course_id:
            continue
        for a in c.get("assignments", []):
            if only_unsubmitted and a.get("submitted"):
                continue
            if cutoff:
                due = datetime.fromisoformat(a["due_at"])
                if due > cutoff:
                    continue
            out.append({**a, "course_id": c["id"], "course_code": c["code"]})
    out.sort(key=lambda a: a["due_at"])
    return out


@router.get("/grades", operation_id="get_grades")
def get_grades(student_id: str = "stu_001") -> list[dict]:
    # dummy-derive: weight * (submitted ? 0.88 : 0.0) per assignment
    out = []
    for c in _student_courses(student_id):
        earned = sum(a.get("weight", 0) * (0.88 if a.get("submitted") else 0) for a in c.get("assignments", []))
        possible_so_far = sum(a.get("weight", 0) for a in c.get("assignments", []) if a.get("submitted"))
        out.append({
            "course_id": c["id"],
            "course_code": c["code"],
            "earned_points": round(earned, 3),
            "possible_points_so_far": round(possible_so_far, 3),
            "letter_estimate": "B+" if possible_so_far == 0 else "A-",
        })
    return out


@router.get("/announcements", operation_id="list_announcements")
def announcements(student_id: str = "stu_001", since: str | None = None) -> list[dict]:
    cutoff = datetime.fromisoformat(since) if since else datetime.now(timezone.utc) - timedelta(days=7)
    out = []
    for c in _student_courses(student_id):
        for an in c.get("announcements", []):
            if datetime.fromisoformat(an["posted_at"]) >= cutoff:
                out.append({**an, "course_id": c["id"], "course_code": c["code"]})
    out.sort(key=lambda a: a["posted_at"], reverse=True)
    return out
