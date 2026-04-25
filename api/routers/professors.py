"""/professors — directory, match, email drafting.

TODO real integration: Testudo Schedule of Classes for current-term teaching
assignments + RateMyProfessors for qualitative signal.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api import store
from api.models import MatchRequest

router = APIRouter(prefix="/professors", tags=["professors"])


@router.get("", operation_id="list_professors")
def list_professors(department: str | None = None, course: str | None = None) -> list[dict]:
    out = store.get("professors")
    if department:
        out = [p for p in out if p.get("department") == department]
    if course:
        out = [p for p in out if course in p.get("current_courses", [])]
    return out


@router.get("/{prof_id}", operation_id="get_professor")
def get_professor(prof_id: str) -> dict:
    p = store.find_one("professors", prof_id)
    if not p:
        raise HTTPException(404, "professor not found")
    return p


@router.post("/match", operation_id="match_professors",
             summary="Which profs fit the student — for research outreach or which class to take")
def match_profs(req: MatchRequest) -> list[dict]:
    s = store.find_one("students", req.student_id) or {}
    interests = {i.lower() for i in (req.interests or s.get("interests", []))}
    ranked = []
    for p in store.get("professors"):
        fields = {f.lower() for f in p.get("research_fields", [])}
        overlap = interests & fields
        why = []
        score = 0.2
        if overlap:
            why.append(f"research overlap: {', '.join(list(overlap)[:3])}")
            score += 0.2 * len(overlap)
        if p.get("takes_ugrad_researchers"):
            why.append("takes undergrad researchers")
            score += 0.15
        if (p.get("rmp_score") or 0) >= 4.3:
            why.append(f"RMP {p['rmp_score']}")
            score += 0.05
        ranked.append({"item": p, "score": round(min(score, 1.0), 3), "why": why, "blockers": []})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[: req.limit]


@router.post("/draft_email", operation_id="draft_professor_email",
             summary="Generate an outreach email tailored to the student's profile")
def draft_email(professor_id: str, purpose: str = "research", student_id: str = "stu_001") -> dict:
    p = store.find_one("professors", professor_id)
    if not p:
        raise HTTPException(404, "prof not found")
    s = store.find_one("students", student_id) or {}
    interests = ", ".join(s.get("interests", [])[:3])
    completed = ", ".join(s.get("completed_courses", [])[-3:])

    # Strip suffixes like III, Jr., PhD when extracting last name.
    _suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v", "phd", "ph.d", "ph.d."}
    tokens = [t for t in p["name"].split() if t.lower().strip(",.") not in _suffixes]
    last_name = tokens[-1] if tokens else p["name"]

    subject_map = {
        "research": f"Undergraduate research interest — {s.get('major','CS')} {s.get('year','undergrad')}",
        "office_hours": "Question about course content",
        "recommendation": "Letter of recommendation request",
    }
    body_map = {
        "research": (
            f"Dear Prof. {last_name},\n\n"
            f"I'm {s.get('name','')}, a {s.get('year','')} studying {s.get('major','')} "
            f"with interests in {interests}. I've recently finished {completed} and have been "
            f"following your work on {', '.join(p.get('research_fields', [])[:2])}.\n\n"
            "I'd love to contribute to your group this summer/fall — I can share a CV and a short "
            "write-up of a related project on request. Do you have any openings for undergraduates?\n\n"
            f"Thanks for your time,\n{s.get('name','')}"
        ),
        "office_hours": (
            f"Dear Prof. {last_name},\n\n"
            "I had a question from lecture — happy to come by office hours, but wanted to sanity check "
            "my intuition in advance. [INSERT QUESTION].\n\nThanks!\n"
            f"{s.get('name','')}"
        ),
        "recommendation": (
            f"Dear Prof. {last_name},\n\n"
            f"I'm applying to [PROGRAM / JOB] and would be honored if you'd write me a letter of "
            f"recommendation. Happy to send my CV, statement, and a brief list of work we've overlapped "
            "on.\n\nDeadline: [DATE].\n\n"
            f"Thanks,\n{s.get('name','')}"
        ),
    }
    return {
        "to": p.get("email"),
        "subject": subject_map.get(purpose, subject_map["research"]),
        "body": body_map.get(purpose, body_map["research"]),
        "professor": p["name"],
    }
