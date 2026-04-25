"""/agent — Testudo, the TerpAgent chat agent.

Two modes, selected automatically:

1. **Claude mode** (when `ANTHROPIC_API_KEY` is set, anthropic SDK installed):
   real LLM agent. Claude Sonnet runs an agentic loop with tool-use, calling
   the TerpAgent endpoints as tools. Holds conversation memory, reasons over
   multi-step requests, talks naturally, takes action.

2. **Heuristic mode** (fallback): regex-based intent matcher. Keeps the demo
   working with no credentials, but limited to phrasings the patterns catch.

Both modes return the same envelope:
  { "reply": str, "actions": [{name, input, result}] }
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from api import store

# Optional .env loading — purely a convenience for local dev.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv()
except ImportError:
    pass

# Optional Anthropic SDK.
try:
    from anthropic import Anthropic  # type: ignore

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
USE_CLAUDE = bool(ANTHROPIC_KEY and _ANTHROPIC_AVAILABLE)

router = APIRouter(prefix="/agent", tags=["agent"])


# ---------------- request / response models ----------------


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    student_id: str = "stu_001"


class AgentAction(BaseModel):
    type: str = "tool_use"
    name: str
    input: dict[str, Any] = {}
    result: Any = None


class ChatReply(BaseModel):
    reply: str
    actions: list[AgentAction] = []
    mode: str = "heuristic"  # or "claude"


# =====================================================================
#  CLAUDE MODE — real LLM agent with tool use
# =====================================================================

SYSTEM_PROMPT = """You are **Testudo**, an autonomous campus agent for a University of Maryland, College Park student. You take action on their behalf using a real toolbelt that wraps every UMD service: Canvas (classes, deadlines, grades), Terplink (events, RSVPs, student orgs), Handshake (internships + full-time), UMD HR (TA/RA/part-time campus jobs), OSFA (scholarships), ResLife + off-campus housing, UMD Libraries (rooms, holds), the professor directory, and travel/transit data.

# Personality

Talk like a friend who knows campus inside out, not a customer service bot. Match the student's energy — casual when they're casual, focused when they're stressed. Use light campus references where they fit (Iribe, McKeldin, STAMP, Eppley, terps). Don't perform enthusiasm. Be sharp and warm.

# Operating principles

1. **Get the profile early.** On any new conversation, call `get_profile` so you can ground recommendations in the student's major, year, GPA, interests, skills, courses, goals, and constraints (budget, no-classes-before, has-vehicle).

2. **Match, don't just list.** Prefer `match_*` tools over `list_*` for recommendations. Match tools return ranked items with `score`, `why` (reasons), and `blockers` (what disqualifies it). Always cite the why-reasons; don't invent them.

3. **Take action without re-asking.** When the student says "yes", "do it", "book that", or even a casual "cool" after you've proposed an action, immediately call the right POST tool (`book_room`, `rsvp_event`, `track_scholarship`, `apply_job`, `save_housing`, `join_group`, `draft_professor_email`). Confirm after the fact, not before.

4. **Multi-step is fine.** A request like "find me a TA role I'd actually get and draft outreach to that prof" is one task — chain `match_ta` then `draft_professor_email` in the same turn.

5. **Be honest about gaps.** If no tool covers what they're asking, say so plainly and offer the closest real option. Examples:
   - Swimming/pool booking → "I can't book pool slots — Eppley Recreation Center handles those at the front desk. ERC is in `list_nearby` if you want hours."
   - Specific dining hall menu → "I don't have dining feeds wired up yet."
   - Anything unverifiable → don't make it up.

6. **Respect the schedule.** Before suggesting events, TA shifts, or trips, check the student's `current_courses` meeting times. Flag conflicts.

7. **Format light.** Reply in 1–3 sentences when possible. Use bullets only for lists of 4+ items. Markdown is fine but don't overdo headers/bold. Don't dump raw JSON. Don't list more than 5 options without being asked.

8. **One next step.** End with a single concrete suggestion ("Want me to RSVP?", "Should I draft the email?") — not a menu.

# IDs and conventions

- The student's ID is always `stu_001`. Pass it whenever a tool accepts `student_id`.
- Today is """ + datetime.now().strftime("%A, %B %-d %Y") + """.
- All times are America/New_York unless stated otherwise.
- Currency is USD.

You are Testudo. Ground every recommendation in tool output. Take action. Be brief."""


# Curated tool spec — every tool maps 1:1 to a router function below.
TOOLS: list[dict[str, Any]] = [
    # ---- profile ----
    {
        "name": "get_profile",
        "description": "Fetch the current student's profile: name, major, minor, year, GPA, hometown, interests, skills, completed courses, current courses, goals, constraints (budget, vehicle, max work hours), friends, and saved items.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_commitments",
        "description": "List the student's saved/tracked items: events RSVP'd, scholarships tracked, jobs applied, housing saved.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_profile_interests",
        "description": "Append interests to the student's profile.",
        "input_schema": {
            "type": "object",
            "properties": {"interests": {"type": "array", "items": {"type": "string"}}},
            "required": ["interests"],
        },
    },
    # ---- canvas ----
    {
        "name": "list_courses",
        "description": "List the student's currently enrolled Canvas courses with meeting times, room, professor, and assignments.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_assignments",
        "description": "List upcoming Canvas assignments. due_within accepts e.g. '2d', '7d', '30d'. course_id filters to one course.",
        "input_schema": {
            "type": "object",
            "properties": {
                "due_within": {"type": "string", "description": "e.g. '7d', '24h'", "default": "7d"},
                "course_id": {"type": "string"},
                "only_unsubmitted": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "list_announcements",
        "description": "Recent announcements from courses. since defaults to the last 7 days.",
        "input_schema": {
            "type": "object",
            "properties": {"since": {"type": "string", "description": "ISO datetime"}},
        },
    },
    {
        "name": "get_grades",
        "description": "Per-course grade summary so far this semester.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    # ---- events / terplink ----
    {
        "name": "list_events",
        "description": "Browse Terplink events. Use for raw browsing — for recommendations, prefer match_events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "tech|arts|cultural|club_sports|career|academic|entrepreneurship|club"},
                "start": {"type": "string", "description": "ISO datetime lower bound"},
                "end": {"type": "string", "description": "ISO datetime upper bound"},
            },
        },
    },
    {
        "name": "match_events",
        "description": "Rank Terplink events for the student by interest overlap, friend overlap, and popularity. Returns items with score (0-1), why (reasons), and blockers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "interests": {"type": "array", "items": {"type": "string"}, "description": "Override student interests for this query"},
                "limit": {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "rsvp_event",
        "description": "RSVP the student to a Terplink event. Use after the student confirms.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "list_orgs",
        "description": "List student organizations / clubs, optionally filtered by topic.",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
        },
    },
    # ---- jobs / TA / RA / part-time ----
    {
        "name": "match_ta",
        "description": "Rank TA openings by completed-course match and GPA. Items in 'blockers' have unmet prereqs.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 5}},
        },
    },
    {
        "name": "match_ra",
        "description": "Rank RA openings by interest/skill overlap.",
        "input_schema": {
            "type": "object",
            "properties": {
                "interests": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "list_part_time",
        "description": "On-campus part-time non-academic jobs (libraries, dining, ERC, etc.).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "match_handshake_jobs",
        "description": "Rank Handshake postings (internships + full-time) by skill/year/GPA fit.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 5}},
        },
    },
    {
        "name": "list_handshake_jobs",
        "description": "Browse Handshake postings filtered by type or keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "internship|fulltime|parttime"},
                "q": {"type": "string"},
                "remote": {"type": "boolean"},
            },
        },
    },
    {
        "name": "save_job",
        "description": "Save a TA/RA/part-time/Handshake job to the student's tracker.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
    # ---- scholarships ----
    {
        "name": "match_scholarships",
        "description": "Rank scholarships by GPA fit, major fit, topic fit, and deadline urgency.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 5}},
        },
    },
    {
        "name": "track_scholarship",
        "description": "Add a scholarship to the student's tracker.",
        "input_schema": {
            "type": "object",
            "properties": {"scholarship_id": {"type": "string"}},
            "required": ["scholarship_id"],
        },
    },
    # ---- housing ----
    {
        "name": "match_housing",
        "description": "Rank housing by budget, walk distance to Iribe, amenities, vehicle requirement.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 5}},
        },
    },
    {
        "name": "list_housing",
        "description": "Browse housing listings with filters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "on_campus|off_campus"},
                "max_rent": {"type": "integer"},
                "bedrooms": {"type": "integer"},
            },
        },
    },
    {
        "name": "save_housing",
        "description": "Save a housing listing to the student's shortlist.",
        "input_schema": {
            "type": "object",
            "properties": {"listing_id": {"type": "string"}},
            "required": ["listing_id"],
        },
    },
    # ---- library ----
    {
        "name": "list_rooms",
        "description": "List study rooms across UMD libraries. capacity and library are optional filters. library options: McKeldin, Hornbake, STEM (EPSL), Iribe Learning Commons.",
        "input_schema": {
            "type": "object",
            "properties": {
                "capacity": {"type": "integer"},
                "library": {"type": "string"},
            },
        },
    },
    {
        "name": "book_room",
        "description": "Book a library study room. start is ISO datetime, duration_min defaults to 60.",
        "input_schema": {
            "type": "object",
            "properties": {
                "room_id": {"type": "string"},
                "start": {"type": "string", "description": "ISO datetime"},
                "duration_min": {"type": "integer", "default": 60},
            },
            "required": ["room_id", "start"],
        },
    },
    {
        "name": "list_holds",
        "description": "Books on hold ready for pickup at UMD libraries.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    # ---- social ----
    {
        "name": "suggest_friends",
        "description": "Rank classmates by overlap with the student. overlap: interests | shared_classes | hometown.",
        "input_schema": {
            "type": "object",
            "properties": {
                "overlap": {"type": "string", "default": "interests"},
                "limit": {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "lookup_classmate",
        "description": "Get a single classmate's profile (interests, current courses, hometown, groups) by first name or full name.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "list_groups",
        "description": "Browse interest groups / project teams / study groups, optionally filtered by topic.",
        "input_schema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
        },
    },
    {
        "name": "join_group",
        "description": "Join a student group.",
        "input_schema": {
            "type": "object",
            "properties": {"group_id": {"type": "string"}},
            "required": ["group_id"],
        },
    },
    # ---- professors ----
    {
        "name": "match_professors",
        "description": "Rank professors by research overlap, accepts undergrad researchers, RMP score. Use to suggest profs for research outreach OR to take a class with.",
        "input_schema": {
            "type": "object",
            "properties": {
                "interests": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 5},
            },
        },
    },
    {
        "name": "draft_professor_email",
        "description": "Draft a personalized outreach email to a professor. purpose: research | office_hours | recommendation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "professor_id": {"type": "string"},
                "purpose": {"type": "string", "default": "research"},
            },
            "required": ["professor_id"],
        },
    },
    {
        "name": "list_professors",
        "description": "Browse the professor directory by department or course taught.",
        "input_schema": {
            "type": "object",
            "properties": {
                "department": {"type": "string"},
                "course": {"type": "string"},
            },
        },
    },
    # ---- travel ----
    {
        "name": "list_nearby",
        "description": "Places near campus — food, outdoors, culture, nightlife. Includes ERC, Hyattsville spots, DC, Baltimore.",
        "input_schema": {
            "type": "object",
            "properties": {
                "radius_mi": {"type": "number", "default": 15},
                "category": {"type": "string"},
            },
        },
    },
    {
        "name": "list_transit",
        "description": "Public-transit options from campus (Metro, MARC, Amtrak, Shuttle-UM).",
        "input_schema": {
            "type": "object",
            "properties": {"to": {"type": "string"}},
        },
    },
    {
        "name": "list_weekend_trips",
        "description": "Weekend trip ideas filterable by max drive hours.",
        "input_schema": {
            "type": "object",
            "properties": {"max_hours": {"type": "number", "default": 3}},
        },
    },
]


def execute_tool(name: str, input_: dict[str, Any], student_id: str) -> Any:
    """Dispatch a tool call to the corresponding router function.

    Returns native Python objects (dicts/lists) — the caller is responsible
    for JSON-serializing back to Claude.
    """
    from api.models import Action, MatchRequest

    inp = dict(input_ or {})

    # ---- profile ----
    if name == "get_profile":
        return store.find_one("students", student_id)
    if name == "list_commitments":
        s = store.find_one("students", student_id) or {}
        return s.get("saved", {})
    if name == "update_profile_interests":
        from api.routers.me import add_interests
        return add_interests(interests=inp.get("interests", []), student_id=student_id)

    # ---- canvas ----
    if name == "list_courses":
        from api.routers.canvas import list_courses
        return list_courses(student_id=student_id)
    if name == "list_assignments":
        from api.routers.canvas import list_assignments
        return list_assignments(student_id=student_id, **inp)
    if name == "list_announcements":
        from api.routers.canvas import announcements
        return announcements(student_id=student_id, **inp)
    if name == "get_grades":
        from api.routers.canvas import get_grades
        return get_grades(student_id=student_id)

    # ---- terplink / events ----
    if name == "list_events":
        from api.routers.terplink import list_events
        return list_events(**inp)
    if name == "match_events":
        from api.routers.terplink import match_events
        return [m if isinstance(m, dict) else m.model_dump() for m in match_events(MatchRequest(student_id=student_id, **inp))]
    if name == "rsvp_event":
        from api.routers.terplink import rsvp
        return rsvp(Action(student_id=student_id, id=inp["event_id"])).model_dump()
    if name == "list_orgs":
        from api.routers.terplink import list_orgs
        return list_orgs(**inp)

    # ---- jobs ----
    if name == "match_ta":
        from api.routers.jobs import match_ta
        return match_ta(MatchRequest(student_id=student_id, **inp))
    if name == "match_ra":
        from api.routers.jobs import match_ra
        return match_ra(MatchRequest(student_id=student_id, **inp))
    if name == "list_part_time":
        from api.routers.jobs import list_part_time
        return list_part_time()
    if name == "list_handshake_jobs":
        from api.routers.handshake import list_jobs
        return list_jobs(**inp)
    if name == "match_handshake_jobs":
        from api.routers.handshake import match_jobs
        return match_jobs(MatchRequest(student_id=student_id, **inp))
    if name == "save_job":
        from api.routers.jobs import apply
        return apply(Action(student_id=student_id, id=inp["job_id"])).model_dump()

    # ---- scholarships ----
    if name == "match_scholarships":
        from api.routers.scholarships import match
        return match(MatchRequest(student_id=student_id, **inp))
    if name == "track_scholarship":
        from api.routers.scholarships import track
        return track(Action(student_id=student_id, id=inp["scholarship_id"])).model_dump()

    # ---- housing ----
    if name == "match_housing":
        from api.routers.housing import match
        return match(MatchRequest(student_id=student_id, **inp))
    if name == "list_housing":
        from api.routers.housing import list_housing
        return list_housing(**inp)
    if name == "save_housing":
        from api.routers.housing import save
        return save(Action(student_id=student_id, id=inp["listing_id"])).model_dump()

    # ---- library ----
    if name == "list_rooms":
        from api.routers.library import list_rooms
        return list_rooms(**inp)
    if name == "book_room":
        from api.routers.library import book_room
        return book_room(
            room_id=inp["room_id"],
            start=inp["start"],
            duration_min=inp.get("duration_min", 60),
            student_id=student_id,
        ).model_dump()
    if name == "list_holds":
        from api.routers.library import holds
        return holds()

    # ---- social ----
    if name == "suggest_friends":
        from api.routers.social import suggest_friends
        return suggest_friends(overlap=inp.get("overlap", "interests"), student_id=student_id, limit=inp.get("limit", 5))
    if name == "lookup_classmate":
        target = inp.get("name", "").lower()
        for c in store.get("classmates"):
            if target == c["name"].split()[0].lower() or target in c["name"].lower():
                return c
        return {"error": f"no classmate matching '{inp.get('name')}'"}
    if name == "list_groups":
        from api.routers.social import list_groups
        return list_groups(**inp)
    if name == "join_group":
        from api.routers.social import join_group
        return join_group(group_id=inp["group_id"], student_id=student_id).model_dump()

    # ---- professors ----
    if name == "match_professors":
        from api.routers.professors import match_profs
        return match_profs(MatchRequest(student_id=student_id, **inp))
    if name == "draft_professor_email":
        from api.routers.professors import draft_email
        return draft_email(
            professor_id=inp["professor_id"],
            purpose=inp.get("purpose", "research"),
            student_id=student_id,
        )
    if name == "list_professors":
        from api.routers.professors import list_professors
        return list_professors(**inp)

    # ---- travel ----
    if name == "list_nearby":
        from api.routers.travel import nearby
        return nearby(**inp)
    if name == "list_transit":
        from api.routers.travel import transit
        return transit(**inp)
    if name == "list_weekend_trips":
        from api.routers.travel import weekend_trips
        return weekend_trips(**inp)

    return {"error": f"unknown tool: {name}"}


def _serialize_assistant_content(blocks: list) -> list[dict]:
    """Convert Anthropic SDK content blocks into wire-format dicts so we can
    feed them back into the next request as the assistant turn."""
    out = []
    for b in blocks:
        if b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return out


def claude_chat(req: ChatRequest) -> ChatReply:
    """Run the Claude tool-use loop.

    Up to 8 rounds of tool calls per user turn. Conversation memory is the
    full `req.messages` list — the UI sends the running history each turn.
    """
    client = Anthropic(api_key=ANTHROPIC_KEY)

    messages: list[dict[str, Any]] = [{"role": m.role, "content": m.content} for m in req.messages]
    actions: list[AgentAction] = []
    final_text = ""

    for _ in range(8):
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if resp.stop_reason == "end_turn":
            final_text = "\n\n".join(b.text for b in resp.content if b.type == "text").strip()
            break

        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": _serialize_assistant_content(resp.content)})
            tool_results: list[dict] = []
            for block in resp.content:
                if block.type == "tool_use":
                    try:
                        result = execute_tool(block.name, dict(block.input), req.student_id)
                    except Exception as e:
                        result = {"error": f"{type(e).__name__}: {e}"}
                    actions.append(AgentAction(name=block.name, input=dict(block.input), result=result))
                    # cap result size so we don't explode the context
                    payload = json.dumps(result, default=str, ensure_ascii=False)
                    if len(payload) > 12000:
                        payload = payload[:12000] + " …(truncated)"
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": payload})
            messages.append({"role": "user", "content": tool_results})
            continue

        # max_tokens or other reason
        final_text = "\n\n".join(b.text for b in resp.content if b.type == "text").strip()
        break

    return ChatReply(reply=final_text or "(no reply)", actions=actions, mode="claude")


# =====================================================================
#  HEURISTIC MODE — regex-based intent matcher (fallback)
# =====================================================================


def _student(sid: str) -> dict:
    return store.find_one("students", sid) or {}


def _classmates() -> list[dict]:
    return store.get("classmates")


def _find_classmate_by_name(name_part: str) -> dict | None:
    name_part = name_part.lower()
    for c in _classmates():
        if name_part in c["name"].lower() or name_part == c["name"].split()[0].lower():
            return c
    return None


def _fmt_dt(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
    except Exception:
        return iso
    return d.strftime("%a %b %-d, %-I:%M %p")


def _parse_time_hint(text: str) -> datetime:
    now = datetime.now()
    t = text.lower()
    target = now.replace(minute=0, second=0, microsecond=0)
    day_off = 1
    if "today" in t or "tonight" in t:
        day_off = 0
    elif "tomorrow" in t:
        day_off = 1
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, wd in enumerate(weekdays):
        if wd in t:
            today = now.weekday()
            diff = (i - today) % 7 or 7
            day_off = diff
            break
    target += timedelta(days=day_off)
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if m:
        h = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3)
        if ampm == "pm" and h < 12:
            h += 12
        if ampm == "am" and h == 12:
            h = 0
        if not ampm and h < 9:
            h += 12
        target = target.replace(hour=h, minute=minute)
    elif "morning" in t:
        target = target.replace(hour=9)
    elif "afternoon" in t:
        target = target.replace(hour=14)
    elif "evening" in t or "night" in t:
        target = target.replace(hour=19)
    else:
        target = target.replace(hour=14)
    return target


def _action(tool_name: str, result: Any, **inp: Any) -> AgentAction:
    return AgentAction(name=tool_name, input=inp, result=result)


def handle_deadlines(sid: str, msg: str) -> ChatReply:
    student = _student(sid)
    m = re.search(r"(?:cmsc|math|stat|ling|bmgt)\s*(\d{3}[a-z]?)", msg)
    course_filter = None
    if m:
        code = re.sub(r"\s+", "", m.group(0)).upper()
        courses = [c for c in store.get("canvas_courses") if c["code"] == code]
        if courses:
            course_filter = courses[0]["id"]
    due_within = "7d"
    if "today" in msg or "tonight" in msg or "48" in msg:
        due_within = "2d"
    elif "month" in msg or "30" in msg:
        due_within = "30d"
    from api.routers.canvas import list_assignments
    items = list_assignments(student_id=sid, course_id=course_filter, due_within=due_within, only_unsubmitted=True)
    if not items:
        return ChatReply(reply=f"You're clear for the next {due_within}. Nothing open.", actions=[_action("list_assignments", items, course_id=course_filter, due_within=due_within)])
    lines = [f"**What's due in the next {due_within}**:"]
    for a in items[:6]:
        d = datetime.fromisoformat(a["due_at"])
        days = (d - datetime.now(timezone.utc)).days
        urgency = "⚠ today" if days <= 0 else f"in {days}d"
        lines.append(f"- {a['course_code']} · **{a['title']}** — {_fmt_dt(a['due_at'])} ({urgency})")
    lines.append("\nWant me to remind you an hour before any of these?")
    return ChatReply(reply="\n".join(lines), actions=[_action("list_assignments", items, course_id=course_filter, due_within=due_within)])


def handle_weekend(sid: str, msg: str) -> ChatReply:
    from api.routers.terplink import match_events
    from api.routers.travel import nearby, weekend_trips
    from api.models import MatchRequest
    events = match_events(MatchRequest(student_id=sid, limit=3))
    nb = nearby(radius_mi=15, category=None)[:3]
    wt = weekend_trips(max_hours=3)[:3]
    lines = ["Here's a weekend plan tuned to your interests:"]
    lines.append("\n**On campus / in CP**")
    for e in events:
        lines.append(f"- {_fmt_dt(e['item']['start'])} — **{e['item']['title']}** at {e['item']['location']} · _{'; '.join(e['why'][:2])}_")
    lines.append("\n**Off-campus nearby**")
    for p in nb:
        lines.append(f"- **{p['name']}** ({p['category']}, {p['distance_mi']} mi) — {p['description']}")
    lines.append("\n**If you want to get out of town (<3h drive)**")
    for t in wt:
        lines.append(f"- **{t['name']}** — {t['drive_hours']}h · {', '.join(t['highlights'])}")
    lines.append("\nSay 'RSVP me to Climb Night' or 'book me a trip to Harpers Ferry' to act on any of these.")
    return ChatReply(reply="\n".join(lines), actions=[_action("match_events", events), _action("list_nearby", nb), _action("list_weekend_trips", wt)])


_LIBRARY_ALIASES = {
    "mckeldin": "McKeldin", "mcklewiden": "McKeldin", "mckwiden": "McKeldin", "mcleod": "McKeldin",
    "hornbake": "Hornbake", "hornblake": "Hornbake",
    "stem": "STEM (EPSL)", "epsl": "STEM (EPSL)",
    "iribe": "Iribe Learning Commons",
    "eppley": "Eppley Recreation Center", "erc": "Eppley Recreation Center",
}


def handle_book_room(sid: str, msg: str) -> ChatReply:
    from api.routers.library import list_rooms, book_room
    lib_name = None
    for alias, canonical in _LIBRARY_ALIASES.items():
        if alias in msg:
            lib_name = canonical
            break
    if lib_name == "Eppley Recreation Center":
        return ChatReply(reply="Eppley Rec doesn't have study rooms — it's the gym/climbing wall. Did you mean the Iribe Learning Commons or McKeldin?", actions=[])
    cap_match = re.search(r"(\d+)\s*(?:person|people|ppl|seats?|-?person)", msg)
    capacity = int(cap_match.group(1)) if cap_match else 4
    dur_match = re.search(r"(\d+)\s*(?:hr|hours?|h)\b", msg)
    duration_min = int(dur_match.group(1)) * 60 if dur_match else 120
    rooms = list_rooms(capacity=capacity, library=lib_name)
    if not rooms:
        rooms = list_rooms(capacity=capacity)
        if not rooms:
            return ChatReply(reply="No rooms matching that capacity. Try a smaller group size?", actions=[])
    room = rooms[0]
    start_dt = _parse_time_hint(msg)
    result = book_room(room_id=room["id"], start=start_dt.isoformat(), duration_min=duration_min, student_id=sid)
    end_dt = start_dt + timedelta(minutes=duration_min)
    reply = (
        f"Booked **{room['library']} Floor {room['floor']}** (room `{room['id']}`, cap {room['capacity']}"
        f"{', monitor' if room.get('has_monitor') else ''}"
        f"{', whiteboard' if room.get('has_whiteboard') else ''}) "
        f"from **{start_dt.strftime('%a %-I:%M %p')}** to **{end_dt.strftime('%-I:%M %p')}**."
    )
    return ChatReply(reply=reply, actions=[_action("book_room", result.model_dump() if hasattr(result, "model_dump") else result, room_id=room["id"], start=start_dt.isoformat(), duration_min=duration_min)])


def handle_friend(sid: str, msg: str) -> ChatReply:
    classmates = _classmates()
    friend = None
    for c in classmates:
        first = c["name"].split()[0].lower()
        if first in msg or c["name"].lower() in msg:
            friend = c
            break
    if not friend:
        m = re.search(r"(?:friend|about)\s+([a-z]+)", msg)
        if m:
            friend = _find_classmate_by_name(m.group(1))
    if not friend:
        return ChatReply(reply="Who do you mean? Say 'what's Priya doing?' or 'tell me about Ade'.", actions=[])
    day_hint = None
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for wd in weekdays:
        if wd in msg:
            day_hint = wd
            break
    courses = [c for c in store.get("canvas_courses") if friend["id"] in c.get("student_ids", [])]
    classes_today = []
    if day_hint:
        abbrev = day_hint[:3].capitalize()
        classes_today = [c for c in courses if abbrev in c.get("meeting_days", [])]
    events = store.get("terplink_events")
    likely_events = []
    interests = set(friend.get("interests", []))
    for e in events:
        if set(e.get("tags", [])) & interests:
            likely_events.append(e)
    likely_events = likely_events[:3]
    lines = [f"**{friend['name']}** — {friend['major']}, {friend['year']}, from {friend.get('hometown','')}"]
    lines.append(f"_Interests:_ {', '.join(friend.get('interests', []))}")
    lines.append(f"_Current classes:_ {', '.join(friend.get('current_courses', []))}")
    if day_hint and classes_today:
        lines.append(f"\n**{day_hint.capitalize()} classes**")
        for c in classes_today:
            lines.append(f"- {c['code']} {c['meeting_time']} · {c['room']}")
    if likely_events:
        lines.append(f"\n**Events they'd likely be at**")
        for e in likely_events:
            lines.append(f"- {_fmt_dt(e['start'])} · **{e['title']}** ({e['location']})")
    lines.append("\nWant me to see if they're free to grab coffee?")
    return ChatReply(reply="\n".join(lines), actions=[_action("lookup_friend", friend, name=friend["name"])])


def handle_events(sid: str, msg: str) -> ChatReply:
    from api.routers.terplink import match_events
    from api.models import MatchRequest
    matches = match_events(MatchRequest(student_id=sid, limit=5))
    lines = ["Top event picks for you:"]
    for m in matches:
        lines.append(f"- **{m['item']['title']}** · {_fmt_dt(m['item']['start'])} · _{'; '.join(m['why'][:2])}_ (score {int(m['score']*100)}%)")
    lines.append("\nSay 'RSVP me to <event name>' to sign up.")
    return ChatReply(reply="\n".join(lines), actions=[_action("match_events", matches)])


def handle_rsvp(sid: str, msg: str) -> ChatReply:
    events = store.get("terplink_events")
    chosen = None
    for e in events:
        if any(tok in msg for tok in [e["title"].lower(), e["id"]]):
            chosen = e
            break
    if not chosen:
        for e in events:
            if e["org"].lower() in msg or any(t in msg for t in e.get("tags", [])):
                chosen = e
                break
    if not chosen:
        return ChatReply(reply="Which event? Name it or paste the title.", actions=[])
    from api.routers.terplink import rsvp
    from api.models import Action
    result = rsvp(Action(student_id=sid, id=chosen["id"]))
    return ChatReply(reply=f"RSVP'd to **{chosen['title']}** — {_fmt_dt(chosen['start'])} at {chosen['location']}.", actions=[_action("rsvp_event", result.model_dump(), id=chosen["id"])])


def handle_jobs(sid: str, msg: str) -> ChatReply:
    from api.routers.jobs import match_ta, match_ra
    from api.models import MatchRequest
    if "ra" in msg or "research" in msg or "lab" in msg:
        r = match_ra(MatchRequest(student_id=sid, limit=4))
        lines = ["Top RA matches:"]
        for m in r:
            lines.append(f"- **{m['item'].get('lab') or m['item'].get('field')}** with {m['item'].get('professor_id','')} · ${m['item']['pay_hourly']}/hr · _{'; '.join(m['why'][:2])}_")
        return ChatReply(reply="\n".join(lines), actions=[_action("match_ra", r)])
    r = match_ta(MatchRequest(student_id=sid, limit=4))
    lines = ["Top TA matches:"]
    for m in r:
        it = m["item"]
        blockers = f" · ⛔ {'; '.join(m['blockers'])}" if m.get("blockers") else ""
        lines.append(f"- **{it['course_code']}** — ${it['pay_hourly']}/hr, apply by {it['deadline']} · _{'; '.join(m['why'][:2])}_{blockers}")
    lines.append("\nSay 'draft outreach to Prof. <name>' for a personalized email.")
    return ChatReply(reply="\n".join(lines), actions=[_action("match_ta", r)])


def handle_scholarships(sid: str, msg: str) -> ChatReply:
    from api.routers.scholarships import match
    from api.models import MatchRequest
    r = match(MatchRequest(student_id=sid, limit=4))
    lines = ["Scholarships ranked by fit + deadline:"]
    for m in r:
        it = m["item"]
        blockers = f" · ⛔ {'; '.join(m['blockers'])}" if m.get("blockers") else ""
        lines.append(f"- **{it['name']}** — ${it['amount']:,}, due {it['deadline']} · _{'; '.join(m['why'][:2])}_{blockers}")
    return ChatReply(reply="\n".join(lines), actions=[_action("match_scholarships", r)])


def handle_housing(sid: str, msg: str) -> ChatReply:
    from api.routers.housing import match
    from api.models import MatchRequest
    r = match(MatchRequest(student_id=sid, limit=4))
    lines = ["Housing ranked for you:"]
    for m in r:
        it = m["item"]
        lines.append(f"- **{it['name']}** · ${it['rent_monthly']}/mo · {it['bedrooms']}BR · {it['distance_to_iribe_min_walk']} min walk · _{'; '.join(m['why'][:2])}_")
    return ChatReply(reply="\n".join(lines), actions=[_action("match_housing", r)])


def handle_profs(sid: str, msg: str) -> ChatReply:
    from api.routers.professors import match_profs, draft_email
    from api.models import MatchRequest
    if "draft" in msg or "email" in msg or "outreach" in msg:
        profs = store.get("professors")
        _suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v", "phd", "ph.d", "ph.d."}
        chosen = None
        for p in profs:
            tokens = [t for t in p["name"].split() if t.lower().strip(",.") not in _suffixes]
            last = tokens[-1].lower() if tokens else ""
            if p["name"].lower() in msg or (last and re.search(rf"\b{re.escape(last)}\b", msg)):
                chosen = p
                break
        if not chosen:
            chosen = match_profs(MatchRequest(student_id=sid, limit=1))[0]["item"]
        draft = draft_email(professor_id=chosen["id"], purpose="research", student_id=sid)
        reply = (
            f"Drafted an email to **{chosen['name']}**:\n\n"
            f"> **To:** {draft['to']}\n> **Subject:** {draft['subject']}\n\n"
            + "\n".join(f"> {ln}" for ln in draft['body'].splitlines())
            + "\n\nWant me to tweak the tone, add a paper reference, or send as-is?"
        )
        return ChatReply(reply=reply, actions=[_action("draft_professor_email", draft, professor_id=chosen["id"])])
    r = match_profs(MatchRequest(student_id=sid, limit=4))
    lines = ["Profs best aligned with your interests:"]
    for m in r:
        it = m["item"]
        lines.append(f"- **{it['name']}** ({it['department']}) · fields: {', '.join(it['research_fields'][:2])} · _{'; '.join(m['why'][:2])}_")
    lines.append("\nSay 'draft email to <name>' and I'll write the outreach.")
    return ChatReply(reply="\n".join(lines), actions=[_action("match_professors", r)])


def handle_travel(sid: str, msg: str) -> ChatReply:
    from api.routers.travel import weekend_trips, nearby, transit
    wt = weekend_trips(max_hours=3)
    nb = nearby(radius_mi=15, category=None)[:3]
    lines = ["Travel ideas:"]
    lines.append("\n**Weekend trips**")
    for t in wt[:4]:
        lines.append(f"- **{t['name']}** · {t['drive_hours']}h · {', '.join(t['highlights'])}")
    lines.append("\n**Close to campus**")
    for p in nb:
        lines.append(f"- **{p['name']}** ({p['category']}, {p['distance_mi']} mi)")
    return ChatReply(reply="\n".join(lines), actions=[_action("list_weekend_trips", wt)])


def handle_profile(sid: str, msg: str) -> ChatReply:
    s = _student(sid)
    lines = [
        f"**{s['name']}** — {s['major']} · {s['year']} · GPA {s['gpa']}",
        f"_Interests:_ {', '.join(s.get('interests', []))}",
        f"_Skills:_ {', '.join(s.get('skills', []))}",
        f"_Goals:_",
        *[f"  · {g}" for g in s.get('goals', [])],
    ]
    return ChatReply(reply="\n".join(lines), actions=[_action("get_profile", s)])


def handle_help(sid: str, msg: str) -> ChatReply:
    return ChatReply(
        reply=(
            "I'm **Testudo** — your UMD agent. I can:\n"
            "- Pull your deadlines: _'what's due this week in CMSC414?'_\n"
            "- Plan your weekend: _'suggest what I should do this weekend'_\n"
            "- Book library rooms: _'book a McKeldin room at 2pm tomorrow for 2 hours'_\n"
            "- Brief you on friends: _'what is Priya up to this Monday?'_\n"
            "- Rank TA/RA/internship fits: _'best TA positions for fall'_\n"
            "- Find scholarships: _'scholarships I should apply to'_\n"
            "- Match housing: _'housing under $1100 near Iribe'_\n"
            "- Draft prof outreach: _'draft an email to Prof. Daume'_\n"
            "- Surface events: _'RSVP me to the Startup Shell demo'_\n\n"
            "_Tip: set `ANTHROPIC_API_KEY` in `.env` to upgrade me to a real reasoning agent that handles open-ended requests._"
        ),
        actions=[],
    )


INTENTS: list[tuple[str, Any]] = [
    (r"\b(who am i|my profile|my interests|about me)\b", handle_profile),
    (r"\b(help|what can you do|how do you work|testudo)\b", handle_help),
    (r"\b(rsvp|sign me up|register me)\b", handle_rsvp),
    (r"\b(book|reserve|schedule).{0,30}(room|library|mckeldin|mcklewiden|mckwiden|hornbake|hornblake|epsl|stem|iribe|eppley|erc)\b", handle_book_room),
    (r"\b(due|deadlines?|to.?dos?|assignments?|homework|hw|project)\b", handle_deadlines),
    (r"\b(weekend|saturday|sunday|what should i do)\b", handle_weekend),
    (r"\b(draft|write).{0,20}(email|outreach|letter)\b", handle_profs),
    (r"\b(profs?|professors?|advisor|mentor|shi|daume|hicks|porter|khuller|padua|hanna|grove)\b", handle_profs),
    (r"\b(ra|research assistant|research position|lab)\b", handle_jobs),
    (r"\b(ta|teaching assistant|part[- ]?time|campus job)\b", handle_jobs),
    (r"\b(intern|internship|full[- ]?time|handshake|new.?grad)\b", handle_jobs),
    (r"\b(scholarships?|funding|awards?|grants?)\b", handle_scholarships),
    (r"\b(housing|house|rent|apartments?|roommates?|dorms?)\b", handle_housing),
    (r"\b(travel|trip|dc|baltimore|annapolis|philly|rehoboth|harpers)\b", handle_travel),
    (r"\b(event|hack night|demo night|climbing|climb|chess|showcase|music)\b", handle_events),
]


def _friend_mentioned(msg: str) -> bool:
    for c in _classmates():
        first = c["name"].split()[0].lower()
        if first and re.search(rf"\b{first}\b", msg):
            return True
    return False


def heuristic_chat(req: ChatRequest) -> ChatReply:
    if not req.messages:
        return handle_help(req.student_id, "")
    last = req.messages[-1].content.lower().strip()
    if _friend_mentioned(last) and re.search(r"\b(doing|plan|up to|class|schedule|taking|free|busy|study|hanging|friend|about)\b", last):
        return handle_friend(req.student_id, last)
    for pattern, handler in INTENTS:
        if re.search(pattern, last):
            try:
                return handler(req.student_id, last)
            except Exception as e:
                return ChatReply(reply=f"I hit an error running that: {e}", actions=[])
    return ChatReply(
        reply=(
            "I can't quite parse that with my keyword rules — but if you set `ANTHROPIC_API_KEY` "
            "in your `.env`, I upgrade to a real reasoning agent and handle open-ended requests. "
            "Otherwise try: _'what's due this week'_, _'plan my weekend'_, _'book a McKeldin room 2pm tomorrow'_, "
            "_'what's Priya doing Monday?'_, _'draft email to Prof. Daume'_, or _help_."
        ),
        actions=[],
    )


# =====================================================================
#  Endpoint
# =====================================================================


@router.post("/chat", operation_id="chat", response_model=ChatReply,
             summary="Chat with Testudo. Uses Claude tool-use if ANTHROPIC_API_KEY is set, else a heuristic matcher.")
def chat(req: ChatRequest) -> ChatReply:
    if USE_CLAUDE:
        try:
            return claude_chat(req)
        except Exception as e:
            # Fall through to heuristic if Claude errors (rate limit, network, etc.)
            reply = heuristic_chat(req)
            reply.reply = f"_(Claude call failed: {type(e).__name__}; falling back to heuristic.)_\n\n{reply.reply}"
            return reply
    return heuristic_chat(req)


@router.get("/mode", operation_id="agent_mode",
            summary="Report whether Testudo is running in heuristic or Claude mode")
def mode() -> dict:
    return {
        "mode": "claude" if USE_CLAUDE else "heuristic",
        "model": ANTHROPIC_MODEL if USE_CLAUDE else None,
        "anthropic_sdk_installed": _ANTHROPIC_AVAILABLE,
        "api_key_present": bool(ANTHROPIC_KEY),
    }
