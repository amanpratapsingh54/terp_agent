"""Smoke tests — hit one endpoint per router."""
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"ok": True}


def test_profile():
    r = client.get("/me")
    assert r.status_code == 200
    assert r.json()["id"] == "stu_001"


def test_assignments_due_soon():
    r = client.get("/canvas/assignments", params={"due_within": "30d"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_match_events():
    r = client.post("/terplink/events/match", json={"student_id": "stu_001", "limit": 3})
    assert r.status_code == 200
    data = r.json()
    assert len(data) <= 3
    if data:
        assert {"item", "score", "why", "blockers"} <= set(data[0].keys())


def test_match_handshake():
    r = client.post("/handshake/jobs/match", json={"student_id": "stu_001", "limit": 2})
    assert r.status_code == 200


def test_match_ta():
    r = client.post("/jobs/ta/match", json={"student_id": "stu_001", "limit": 2})
    assert r.status_code == 200


def test_match_scholarships():
    r = client.post("/scholarships/match", json={"student_id": "stu_001", "limit": 2})
    assert r.status_code == 200


def test_housing_match():
    r = client.post("/housing/match", json={"student_id": "stu_001", "limit": 2})
    assert r.status_code == 200


def test_friends_suggest():
    r = client.post("/social/friends/suggest", params={"student_id": "stu_001", "limit": 3})
    assert r.status_code == 200


def test_match_profs():
    r = client.post("/professors/match", json={"student_id": "stu_001", "limit": 2})
    assert r.status_code == 200


def test_draft_email():
    r = client.post("/professors/draft_email", params={"professor_id": "prof_daume", "purpose": "research"})
    assert r.status_code == 200
    assert "Prof." in r.json()["body"]


def test_library_rooms():
    r = client.get("/library/rooms")
    assert r.status_code == 200


def test_nearby():
    r = client.get("/travel/nearby", params={"radius_mi": 15})
    assert r.status_code == 200
