"""/handshake — full-time, part-time, internship listings.

TODO real integration: Handshake Partner API requires institutional creds.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from api import store
from api.models import Action, MatchRequest, OK

router = APIRouter(prefix="/handshake", tags=["handshake"])

_YEAR_ORDER = {"freshman": 1, "sophomore": 2, "junior": 3, "senior": 4}


@router.get("/jobs", operation_id="list_handshake_jobs")
def list_jobs(type: str | None = None, q: str | None = None, remote: bool | None = None) -> list[dict]:
    out = store.get("handshake_jobs")
    if type:
        out = [j for j in out if j.get("type") == type]
    if remote is not None:
        out = [j for j in out if j.get("remote") == remote]
    if q:
        ql = q.lower()
        out = [j for j in out if ql in j["title"].lower() or ql in j["company"].lower()
               or any(ql in t for t in j.get("tags", []))]
    return out


@router.get("/jobs/{job_id}", operation_id="get_handshake_job")
def get_job(job_id: str) -> dict:
    j = store.find_one("handshake_jobs", job_id)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@router.post("/jobs/match", operation_id="match_handshake_jobs",
             summary="Rank Handshake postings against the student's skills/major/year/GPA")
def match_jobs(req: MatchRequest) -> list[dict]:
    s = store.find_one("students", req.student_id) or {}
    student_skills = {sk.lower() for sk in s.get("skills", [])}
    student_year = _YEAR_ORDER.get(s.get("year", "freshman"), 1)
    student_gpa = s.get("gpa", 0.0)

    ranked = []
    for j in store.get("handshake_jobs"):
        why: list[str] = []
        blockers: list[str] = []
        score = 0.2

        wanted = {sk.lower() for sk in j.get("skills_wanted", [])}
        overlap = student_skills & wanted
        if overlap:
            score += 0.15 * len(overlap)
            why.append(f"skill match: {', '.join(list(overlap)[:3])}")

        job_min = _YEAR_ORDER.get(j.get("min_year", "freshman"), 1)
        if student_year >= job_min:
            score += 0.1
        else:
            blockers.append(f"requires {j['min_year']}, you are {s.get('year')}")

        gpa_min = j.get("gpa_min")
        if gpa_min is None or student_gpa >= gpa_min:
            if gpa_min:
                why.append(f"GPA {student_gpa} ≥ {gpa_min}")
        else:
            blockers.append(f"GPA min {gpa_min}, you have {student_gpa}")

        days_left = (date.fromisoformat(j["deadline"]) - date.today()).days
        if days_left < 0:
            blockers.append("deadline passed")
        elif days_left < 7:
            why.append(f"deadline in {days_left}d")
            score += 0.05

        if j.get("pay_hourly", 0) >= 50 or j.get("salary_annual", 0) >= 150000:
            why.append("high comp")
            score += 0.03

        if not blockers:
            score += 0.1
        else:
            score = max(0.0, score - 0.25)

        ranked.append({
            "item": j,
            "score": round(min(score, 1.0), 3),
            "why": why,
            "blockers": blockers,
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[: req.limit]


@router.post("/jobs/apply", operation_id="apply_handshake_job", response_model=OK)
def apply_job(action: Action) -> OK:
    s = store.find_one("students", action.student_id)
    if not s:
        raise HTTPException(404, "student not found")
    s.setdefault("saved", {}).setdefault("jobs", []).append(action.id)
    return OK(message=f"Queued application to {action.id}. Complete it in Handshake.")
