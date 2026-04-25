"""/scholarships — search, match, track applications.

TODO real integration: OSFA + Maryland external scholarship feeds + UMD
scholarship database.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from api import store
from api.models import Action, MatchRequest, OK

router = APIRouter(prefix="/scholarships", tags=["scholarships"])


@router.get("", operation_id="list_scholarships")
def list_scholarships(category: str | None = None) -> list[dict]:
    out = store.get("scholarships")
    return [sc for sc in out if category is None or sc.get("category") == category]


@router.get("/{sch_id}", operation_id="get_scholarship")
def get_scholarship(sch_id: str) -> dict:
    s = store.find_one("scholarships", sch_id)
    if not s:
        raise HTTPException(404, "scholarship not found")
    return s


@router.post("/match", operation_id="match_scholarships")
def match(req: MatchRequest) -> list[dict]:
    s = store.find_one("students", req.student_id) or {}
    gpa = s.get("gpa", 0.0)
    tags = set((req.interests or s.get("interests", [])))
    major = (s.get("major") or "").lower()
    ranked = []
    for sc in store.get("scholarships"):
        why, blockers = [], []
        score = 0.25
        if sc.get("gpa_min") and gpa >= sc["gpa_min"]:
            why.append(f"GPA {gpa} ≥ {sc['gpa_min']}")
            score += 0.15
        elif sc.get("gpa_min") and gpa < sc["gpa_min"]:
            blockers.append(f"GPA below {sc['gpa_min']}")
        if any(t in (sc.get("tags") or []) for t in ["cs", "math", "stat"]) and ("computer science" in major or "math" in major):
            why.append("major fit")
            score += 0.15
        if set(sc.get("tags", [])) & {t.lower() for t in tags}:
            why.append("topic fit")
            score += 0.1
        days_left = (date.fromisoformat(sc["deadline"]) - date.today()).days
        if days_left < 0:
            blockers.append("deadline passed")
        elif days_left <= 14:
            why.append(f"deadline in {days_left}d — act fast")
            score += 0.1
        ranked.append({"item": sc, "score": round(min(score, 1.0), 3), "why": why, "blockers": blockers})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[: req.limit]


@router.post("/track", operation_id="track_scholarship", response_model=OK)
def track(action: Action) -> OK:
    s = store.find_one("students", action.student_id)
    if not s:
        raise HTTPException(404, "student not found")
    s.setdefault("saved", {}).setdefault("scholarships", []).append(action.id)
    return OK(message=f"Tracking {action.id}")


@router.get("/tracked", operation_id="list_tracked")
def tracked(student_id: str = "stu_001") -> list[dict]:
    s = store.find_one("students", student_id) or {}
    ids = s.get("saved", {}).get("scholarships", [])
    return [store.find_one("scholarships", i) for i in ids if store.find_one("scholarships", i)]
