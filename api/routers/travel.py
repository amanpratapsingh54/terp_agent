"""/travel — nearby trips, transit, weekend ideas.

TODO real integration: Google Places for nearby, WMATA API for Metro/Bus,
MTA Maryland for MARC, Amtrak for regional rail.
"""
from __future__ import annotations

from fastapi import APIRouter

from api import store

router = APIRouter(prefix="/travel", tags=["travel"])


@router.get("/nearby", operation_id="list_nearby")
def nearby(radius_mi: float = 15.0, category: str | None = None) -> list[dict]:
    data = store.get("travel") if isinstance(store.get("travel"), dict) else {}
    out = data.get("nearby", [])
    out = [p for p in out if p.get("distance_mi", 0) <= radius_mi]
    if category:
        out = [p for p in out if p.get("category") == category]
    return out


@router.get("/transit", operation_id="list_transit")
def transit(to: str | None = None) -> list[dict]:
    data = store.get("travel") if isinstance(store.get("travel"), dict) else {}
    out = data.get("transit", [])
    if to:
        out = [t for t in out if to.lower() in t.get("to", "").lower()]
    return out


@router.get("/weekend_trips", operation_id="list_weekend_trips")
def weekend_trips(max_hours: float = 3.0) -> list[dict]:
    data = store.get("travel") if isinstance(store.get("travel"), dict) else {}
    return [t for t in data.get("weekend_trips", []) if t.get("drive_hours", 0) <= max_hours]
