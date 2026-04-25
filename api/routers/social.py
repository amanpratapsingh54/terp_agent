"""/social — friend suggestions, interest groups, classmates.

TODO real integration: pipe from Terplink memberships + Canvas rosters
(requires opt-in per FERPA).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api import store
from api.models import OK

router = APIRouter(prefix="/social", tags=["social"])


@router.post("/friends/suggest", operation_id="suggest_friends",
             summary="Rank classmates by shared classes, interests, orgs, or hometown")
def suggest_friends(overlap: str = "interests", student_id: str = "stu_001", limit: int = 5) -> list[dict]:
    s = store.find_one("students", student_id)
    if not s:
        raise HTTPException(404, "student not found")
    candidates = [c for c in store.get("classmates") if c.get("opted_in_social") and c["id"] != student_id]

    def score_overlap(c: dict) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0
        shared_classes = set(s.get("current_courses", [])) & set(c.get("current_courses", []))
        if shared_classes:
            reasons.append(f"shares classes: {', '.join(sorted(shared_classes))}")
            score += 0.15 * len(shared_classes)
        shared_int = set(s.get("interests", [])) & set(c.get("interests", []))
        if shared_int:
            reasons.append(f"shared interests: {', '.join(sorted(shared_int)[:3])}")
            score += 0.1 * len(shared_int)
        shared_hometown = s.get("hometown") and s["hometown"] == c.get("hometown")
        if shared_hometown:
            reasons.append(f"same hometown: {c['hometown']}")
            score += 0.1
        return score, reasons

    ranked = []
    for c in candidates:
        score, why = score_overlap(c)
        if overlap == "shared_classes":
            score += 0.1 * len(set(s.get("current_courses", [])) & set(c.get("current_courses", [])))
        elif overlap == "hometown":
            if s.get("hometown") == c.get("hometown"):
                score += 0.2
        ranked.append({"item": c, "score": round(min(score, 1.0), 3), "why": why, "blockers": []})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:limit]


@router.get("/groups", operation_id="list_groups")
def list_groups(topic: str | None = None) -> list[dict]:
    out = store.get("groups")
    if topic:
        ql = topic.lower()
        out = [g for g in out if ql in (g.get("topic") or "").lower() or ql in g.get("name", "").lower()]
    return out


@router.post("/groups/{group_id}/join", operation_id="join_group", response_model=OK)
def join_group(group_id: str, student_id: str = "stu_001") -> OK:
    g = store.find_one("groups", group_id)
    if not g:
        raise HTTPException(404, "group not found")
    g["members"] = g.get("members", 0) + 1
    return OK(message=f"Joined {g['name']}")


@router.get("/classmates", operation_id="list_classmates")
def classmates(course_id: str, student_id: str = "stu_001") -> list[dict]:
    course = store.find_one("canvas_courses", course_id)
    if not course:
        raise HTTPException(404, "course not found")
    ids = set(course.get("student_ids", [])) - {student_id}
    cm_by_id = {c["id"]: c for c in store.get("classmates")}
    return [cm_by_id[i] for i in ids if i in cm_by_id and cm_by_id[i].get("opted_in_social")]
