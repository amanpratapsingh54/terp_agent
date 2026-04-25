"""/jobs — TA, RA, and campus part-time positions.

Unlike /handshake (external employers), this is the on-campus academic/work
world: TAs, RAs, library desk jobs, dining, ERC.

TODO real integration: UMD HR + per-department TA/RA boards. Many CS TA
applications are just a Google Form linked from the prof's page — keep the
schema here stable and have the real integration fill `apply_url`.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from api import store
from api.models import Action, MatchRequest, OK

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _filter_kind(kind: str, department: str | None = None, course: str | None = None,
                 lab: str | None = None, field: str | None = None) -> list[dict]:
    out = [p for p in store.get("ta_ra_positions") if p.get("kind") == kind]
    if department:
        out = [p for p in out if p.get("department") == department]
    if course:
        out = [p for p in out if p.get("course_code") == course]
    if lab:
        out = [p for p in out if lab.lower() in (p.get("lab") or "").lower()]
    if field:
        out = [p for p in out if p.get("field") == field]
    return out


@router.get("/ta", operation_id="list_ta_positions")
def list_ta(department: str | None = None, course: str | None = None) -> list[dict]:
    return _filter_kind("ta", department=department, course=course)


@router.get("/ra", operation_id="list_ra_positions")
def list_ra(lab: str | None = None, field: str | None = None) -> list[dict]:
    return _filter_kind("ra", lab=lab, field=field)


@router.get("/part_time", operation_id="list_part_time")
def list_part_time() -> list[dict]:
    return [p for p in store.get("ta_ra_positions") if p.get("kind") == "part_time"]


@router.get("/{position_id}", operation_id="get_position")
def get_position(position_id: str) -> dict:
    p = store.find_one("ta_ra_positions", position_id)
    if not p:
        raise HTTPException(404, "position not found")
    return p


@router.post("/ta/match", operation_id="match_ta")
def match_ta(req: MatchRequest) -> list[dict]:
    s = store.find_one("students", req.student_id) or {}
    completed = set(s.get("completed_courses", []))
    gpa = s.get("gpa", 0.0)
    ranked = []
    for p in store.get("ta_ra_positions"):
        if p["kind"] != "ta":
            continue
        why: list[str] = []
        blockers: list[str] = []
        score = 0.25

        if p.get("course_code") in completed:
            why.append(f"you took {p['course_code']}")
            score += 0.35
        else:
            blockers.append(f"prereq: completed {p['course_code']}")

        if gpa >= 3.5:
            why.append(f"strong GPA {gpa}")
            score += 0.1

        days_left = (date.fromisoformat(p["deadline"]) - date.today()).days
        if 0 <= days_left <= 14:
            why.append(f"deadline in {days_left}d")
            score += 0.05

        if not blockers:
            score += 0.1
        else:
            score = max(0.0, score - 0.2)

        ranked.append({"item": p, "score": round(min(score, 1.0), 3), "why": why, "blockers": blockers})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[: req.limit]


@router.post("/ra/match", operation_id="match_ra")
def match_ra(req: MatchRequest) -> list[dict]:
    s = store.find_one("students", req.student_id) or {}
    interests = {i.lower() for i in (req.interests or s.get("interests", []))}
    skills = {sk.lower() for sk in s.get("skills", [])}
    ranked = []
    for p in store.get("ta_ra_positions"):
        if p["kind"] != "ra":
            continue
        why, blockers = [], []
        score = 0.25
        if p.get("field") in interests:
            why.append(f"aligned with interest: {p['field']}")
            score += 0.3
        prereq_hits = [pr for pr in p.get("prereqs", []) if any(s2 in pr.lower() for s2 in skills)]
        if prereq_hits:
            why.append(f"matches skills: {', '.join(prereq_hits[:2])}")
            score += 0.15
        ranked.append({"item": p, "score": round(min(score, 1.0), 3), "why": why, "blockers": blockers})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[: req.limit]


@router.post("/apply", operation_id="apply_job", response_model=OK)
def apply(action: Action) -> OK:
    s = store.find_one("students", action.student_id)
    if not s:
        raise HTTPException(404, "student not found")
    s.setdefault("saved", {}).setdefault("jobs", []).append(action.id)
    return OK(message=f"Saved intent to apply to {action.id}. Draft an outreach email via /professors/draft_email.")
