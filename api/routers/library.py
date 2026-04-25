"""/library — study rooms, holds, databases.

TODO real integration: UMD Libraries Springshare (LibCal) for room booking,
Alma for holds/checkouts.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from api import store
from api.models import OK

router = APIRouter(prefix="/library", tags=["library"])


@router.get("/rooms", operation_id="list_rooms")
def list_rooms(capacity: int | None = None, library: str | None = None) -> list[dict]:
    rooms = store.get("library").get("rooms", []) if isinstance(store.get("library"), dict) else []
    if capacity:
        rooms = [r for r in rooms if r.get("capacity", 0) >= capacity]
    if library:
        rooms = [r for r in rooms if r.get("library") == library]
    return rooms


@router.post("/book", operation_id="book_room", response_model=OK)
def book_room(room_id: str, start: str, duration_min: int = 60, student_id: str = "stu_001") -> OK:
    lib = store.get("library")
    if not isinstance(lib, dict):
        raise HTTPException(500, "library seed malformed")
    rooms = lib.get("rooms", [])
    if not any(r["id"] == room_id for r in rooms):
        raise HTTPException(404, "room not found")
    start_dt = datetime.fromisoformat(start)
    end_dt = start_dt + timedelta(minutes=duration_min)
    booking = {
        "id": f"bkg_{uuid4().hex[:8]}",
        "room_id": room_id,
        "student_id": student_id,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
    }
    lib.setdefault("bookings", []).append(booking)
    return OK(message=f"Booked {room_id} from {start_dt.strftime('%a %H:%M')} to {end_dt.strftime('%H:%M')}")


@router.get("/holds", operation_id="list_holds")
def holds() -> list[dict]:
    lib = store.get("library")
    return lib.get("holds", []) if isinstance(lib, dict) else []


@router.get("/databases", operation_id="list_databases")
def databases(field: str | None = None) -> list[dict]:
    lib = store.get("library")
    dbs = lib.get("databases", []) if isinstance(lib, dict) else []
    if field:
        dbs = [d for d in dbs if field in (d.get("field") or "")]
    return dbs
