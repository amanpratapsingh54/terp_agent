"""/terplink — events + student orgs.

TODO real integration: Terplink runs on CampusGroups. Use the CampusGroups
iCalendar feed for events; scrape /organizations for the org directory.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from api import store
from api.models import Action, MatchRequest, OK

router = APIRouter(prefix="/terplink", tags=["terplink"])


@router.get("/events", operation_id="list_events")
def list_events(category: str | None = None, start: str | None = None, end: str | None = None) -> list[dict]:
    out = store.get("terplink_events")
    if category:
        out = [e for e in out if e.get("category") == category]
    if start:
        s = datetime.fromisoformat(start)
        out = [e for e in out if datetime.fromisoformat(e["start"]) >= s]
    if end:
        en = datetime.fromisoformat(end)
        out = [e for e in out if datetime.fromisoformat(e["end"]) <= en]
    return out


@router.get("/events/{event_id}", operation_id="get_event")
def get_event(event_id: str) -> dict:
    e = store.find_one("terplink_events", event_id)
    if not e:
        raise HTTPException(404, "event not found")
    return e


@router.post("/events/match", operation_id="match_events",
             summary="Rank events against the student profile")
def match_events(req: MatchRequest) -> list[dict]:
    student = store.find_one("students", req.student_id) or {}
    interests = set((req.interests or []) + student.get("interests", []))
    friends = set(req.friends or student.get("friends", []))
    classmates = {c["id"]: c for c in store.get("classmates")}

    ranked = []
    for e in store.get("terplink_events"):
        tags = set(e.get("tags", []) + [e.get("category", "")])
        overlap = interests & tags
        score = min(1.0, 0.2 + 0.15 * len(overlap))
        why = []
        if overlap:
            why.append(f"matches your interests: {', '.join(list(overlap)[:3])}")

        friends_going = [
            classmates[f]["name"] for f in friends
            if f in classmates and any(grp in classmates[f].get("groups", []) for grp in [])
        ]
        # Use a lightweight "friends likely to attend" heuristic: overlap of their interests with event tags.
        friends_going = []
        for f in friends:
            if f in classmates and set(classmates[f].get("interests", [])) & tags:
                friends_going.append(classmates[f]["name"])
                score += 0.08
        if friends_going:
            why.append(f"friends likely going: {', '.join(friends_going[:3])}")

        if e.get("rsvp_count", 0) > 100:
            why.append("popular this week")
            score += 0.03

        ranked.append({"item": e, "score": round(min(score, 1.0), 3), "why": why, "blockers": []})

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[: req.limit]


@router.post("/rsvp", operation_id="rsvp_event", response_model=OK)
def rsvp(action: Action) -> OK:
    s = store.find_one("students", action.student_id)
    if not s:
        raise HTTPException(404, "student not found")
    saved = s.setdefault("saved", {}).setdefault("events", [])
    if action.id not in saved:
        saved.append(action.id)
    return OK(message=f"RSVP'd to {action.id}")


@router.get("/orgs", operation_id="list_orgs")
def list_orgs(category: str | None = None) -> list[dict]:
    groups = store.get("groups")
    if category:
        return [g for g in groups if g.get("topic") == category]
    return groups
