# TerpAgent — Your Autonomous College Life Agent (UMD)

TerpAgent is an autonomous agent built for Claude Cowork that automates a University of Maryland student's full semester — classes, deadlines, TA/RA/part-time jobs, events, scholarships, housing, social recommendations, professor matching, and travel — by unifying fragmented campus services behind **one OpenAPI-compatible server**.

It replaces dozens of siloed portals (Canvas, Terplink, Handshake, Testudo, individual professor pages, scholarship databases, the library, housing) with a single `GET`/`POST` surface that Claude calls directly.

## What's in this repo

```
terp-agent/
├── README.md                 You are here
├── CLAUDE_COWORK_PROMPT.md   The system prompt for the Claude Cowork agent
├── docker-compose.yml        One-command deploy
├── Dockerfile                Python 3.11 + FastAPI
├── requirements.txt
├── api/
│   ├── main.py               FastAPI entry, wires all routers
│   ├── models.py             Pydantic schemas shared across routers
│   ├── store.py              In-memory datastore loaded from /data
│   └── routers/
│       ├── canvas.py         Courses, assignments, deadlines, grades
│       ├── terplink.py       Student orgs + events (UMD's activity hub)
│       ├── handshake.py      Full/part-time + internship listings
│       ├── jobs.py           TA/RA/campus-job postings
│       ├── scholarships.py   Scholarship search + application tracker
│       ├── housing.py        On/off-campus housing matching
│       ├── library.py        Study room bookings, checkouts, holds
│       ├── social.py         Friend suggestions, interest groups
│       ├── professors.py     Prof directory, ratings, class suggestions
│       ├── travel.py         Nearby trips, transit, weekend ideas
│       └── me.py             /me profile, preferences, saved items
├── data/                     JSON seed data (realistic UMD dummy data)
│   ├── students.json
│   ├── canvas_courses.json
│   ├── terplink_events.json
│   ├── handshake_jobs.json
│   ├── ta_ra_positions.json
│   ├── scholarships.json
│   ├── housing.json
│   ├── library.json
│   ├── professors.json
│   ├── travel.json
│   └── groups.json
├── agent/
│   ├── tools.json            OpenAI/Anthropic-style tool specs
│   └── example_queries.md    Prompts you can try
└── tests/
    └── test_api.py           Smoke tests
```

## Quick start

### Local

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8080
# UI:       http://localhost:8080/app
# API docs: http://localhost:8080/docs
```

### Upgrading Testudo to a real LLM agent

Out of the box, Testudo (the chat widget in the lower-right of `/app`) runs in **heuristic mode** — fast and free, but limited to phrasings the regex matcher knows. To upgrade to a real Claude tool-use agent that reasons, holds conversation memory, and handles open-ended requests:

```bash
cp .env.example .env
# edit .env and paste your Anthropic key:
#   ANTHROPIC_API_KEY=sk-ant-...
pip install -r requirements.txt   # picks up anthropic + python-dotenv
uvicorn api.main:app --reload --port 8080
```

When `ANTHROPIC_API_KEY` is set, the chat header in the UI will show **"Claude · sonnet-4-5"** instead of "heuristic mode". Verify with:

```bash
curl http://localhost:8080/agent/mode
# {"mode":"claude","model":"claude-sonnet-4-5-20250929",...}
```

The Claude agent runs an agentic loop with ~30 tools wrapping every TerpAgent endpoint, so it can chain calls (e.g. *"find me a TA role I'd actually get and draft outreach to that prof"* → `match_ta` → `draft_professor_email` in one turn). If a Claude call fails (rate limit, network), the endpoint transparently falls back to heuristic mode and tells you that's what happened.

### What you'll see in the UI

A single-page dashboard (served from `/app`) with a sidebar of panels that each exercise a different router — a live control surface for everything the Claude agent sees. Panels: **Dashboard**, **Classes**, **Events**, **TA/RA/Jobs**, **Internships**, **Scholarships**, **Housing**, **Friends & Groups**, **Professors**, **Library**, **Travel**. Every `/match` result renders with a score bar, the `why` bullets, and red chips for any `blockers`. Action buttons (RSVP, apply, track, save, book, draft-email, join-group) hit the matching `POST` endpoint and toast on success. No build step — a single `ui/index.html` + Tailwind CDN.

### Docker

```bash
docker compose up --build
# API at http://localhost:8080
```

### Deploy anywhere

The project is a stock FastAPI + in-memory JSON app — it runs on Railway, Render, Fly.io, Google Cloud Run, or an EC2 box without changes. Swap `store.py` for Postgres/Redis when you need persistence; all routers already read through that single module.

## The OpenAPI surface (what Claude calls)

Every service exposes a consistent shape: `GET /<service>` to browse, `GET /<service>/{id}` for details, `POST /<service>/match` for personalized ranking against the student's profile, and (where it makes sense) `POST /<service>/save` to pin something.

| Service       | Example endpoints |
|---------------|-------------------|
| Canvas        | `GET /canvas/courses`, `GET /canvas/assignments?due_within=7d`, `GET /canvas/grades` |
| Terplink      | `GET /terplink/events`, `POST /terplink/events/match`, `POST /terplink/rsvp` |
| Handshake     | `GET /handshake/jobs?type=internship`, `POST /handshake/jobs/match` |
| Campus jobs   | `GET /jobs/ta`, `GET /jobs/ra`, `GET /jobs/part_time` |
| Scholarships  | `GET /scholarships`, `POST /scholarships/match`, `POST /scholarships/track` |
| Housing       | `GET /housing?type=off_campus`, `POST /housing/match` |
| Library       | `GET /library/rooms?when=2026-04-25T14:00`, `POST /library/book` |
| Social        | `POST /social/friends/suggest`, `GET /social/groups` |
| Professors    | `GET /professors`, `POST /professors/match` (picks profs by student interests) |
| Travel        | `GET /travel/nearby?radius_mi=50`, `GET /travel/transit` |
| Profile       | `GET /me`, `PATCH /me`, `POST /me/interests` |

Full auto-generated docs live at `/docs` once the server is running.

## Real-integration roadmap

The dummy API mirrors the real UMD surfaces 1:1 so that replacing each router is a drop-in:

| Dummy router     | Real integration |
|------------------|------------------|
| `canvas.py`      | Canvas LMS REST API (OAuth2 w/ UMD ELMS) |
| `terplink.py`    | Terplink (CampusGroups) public API + scraping fallback |
| `handshake.py`   | Handshake Partner API |
| `jobs.py`        | eTerp / UMD HR + individual department boards |
| `scholarships.py`| OSFA + Maryland external scholarship feeds |
| `housing.py`     | ResLife + off-campus housing (OCH) + Zillow/Apartments.com |
| `library.py`     | UMD Libraries Springshare + Alma |
| `professors.py`  | Testudo Schedule of Classes + RateMyProfessors |
| `travel.py`      | MTA Maryland + Amtrak + Google Places |

Each router has a `# TODO: real integration` block showing which endpoint to call.
