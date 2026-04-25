"""/housing — on/off-campus housing search + personalized match.

TODO real integration: ResLife + OCH + Zillow/Apartments.com scrapers.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api import store
from api.models import Action, MatchRequest, OK

router = APIRouter(prefix="/housing", tags=["housing"])


@router.get("", operation_id="list_housing")
def list_housing(type: str | None = None, max_rent: int | None = None, bedrooms: int | None = None) -> list[dict]:
    out = store.get("housing")
    if type:
        out = [h for h in out if h.get("type") == type]
    if max_rent:
        out = [h for h in out if h.get("rent_monthly", 0) <= max_rent]
    if bedrooms:
        out = [h for h in out if h.get("bedrooms") == bedrooms]
    return out


@router.get("/{listing_id}", operation_id="get_housing")
def get_housing(listing_id: str) -> dict:
    h = store.find_one("housing", listing_id)
    if not h:
        raise HTTPException(404, "listing not found")
    return h


@router.post("/match", operation_id="match_housing")
def match(req: MatchRequest) -> list[dict]:
    s = store.find_one("students", req.student_id) or {}
    budget = s.get("constraints", {}).get("budget_monthly_rent", 1200)
    has_car = s.get("constraints", {}).get("vehicle", False)
    ranked = []
    for h in store.get("housing"):
        why, blockers = [], []
        score = 0.2
        if h["rent_monthly"] <= budget:
            why.append(f"within budget (${h['rent_monthly']} ≤ ${budget})")
            score += 0.25
        else:
            blockers.append(f"over budget by ${h['rent_monthly'] - budget}/mo")
        walk = h.get("distance_to_iribe_min_walk", 99)
        if walk <= 10:
            why.append(f"{walk} min walk to Iribe")
            score += 0.25
        elif walk <= 15 or has_car:
            score += 0.1
        else:
            blockers.append(f"{walk} min walk, no vehicle")
        amenities = set(h.get("amenities", []))
        if {"in-unit laundry", "furnished", "a/c"} & amenities:
            why.append("good amenities")
            score += 0.05
        ranked.append({"item": h, "score": round(min(score, 1.0), 3), "why": why, "blockers": blockers})
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[: req.limit]


@router.post("/save", operation_id="save_housing", response_model=OK)
def save(action: Action) -> OK:
    s = store.find_one("students", action.student_id)
    if not s:
        raise HTTPException(404, "student not found")
    s.setdefault("saved", {}).setdefault("housing", []).append(action.id)
    return OK(message=f"Saved {action.id}")
