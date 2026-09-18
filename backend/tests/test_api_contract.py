"""
API contract tests -- the wire shapes the React frontend depends on.

These exist because the planned live A/B diff against the Node backend is impossible on
this machine: better-sqlite3@11.10.0 ships no prebuilt for Node v24 and needs MSVC build
tools, so `npm install` in backend/ fails outright. Every expectation below is therefore
derived from reading the Express source directly (backend/src/routes/*.js), not from
observing a running Node server.

What each assertion pins down: status code, JSON key names, and error message text --
the three things a port silently changes and the frontend silently breaks on.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient whose data/sessions live in tmp_path.

    The service modules bind their paths at import time (like the Node modules did), so
    the fixture rebinds those names rather than mutating config after the fact.
    """
    from app.core import boot as boot_module
    from app.core import config as config_module
    from app.services import profile as profile_module
    from app.services import sessions as sessions_module

    data_dir = tmp_path / "data"
    sessions_dir = tmp_path / "sessions"

    monkeypatch.setattr(config_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(boot_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(boot_module, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(boot_module, "DB_PATH", data_dir / "boppai.db")
    monkeypatch.setattr(sessions_module, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(profile_module, "PROFILE_PATH", data_dir / "profile.md")

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


CALENDAR = {
    "weeks": [
        {
            "id": "week-1",
            "title": "Week 1",
            "startDate": "Aug 3",
            "endDate": "Aug 9",
            "days": [{"day": "Monday", "breakfast": {"name": "Oats", "calories": "~300 kcal"}}],
        }
    ]
}

BASKET = {
    "items": [
        {
            "ingredient": "Tomato",
            "quantity": "2 kg",
            "status": "found",
            "count": 2,
            "product": {"name": "Fresh Tomatoes 1 kg", "packSize": "1 kg", "price": "₹40"},
        }
    ]
}


# --- health ----------------------------------------------------------------


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


# --- profile ---------------------------------------------------------------


def test_profile_starts_empty(client):
    response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json() == {"exists": False, "markdown": "", "name": None}


def test_profile_save_and_read_back(client):
    saved = client.put("/api/profile", json={"markdown": "# Ana\n\n- Diet: vegetarian\n"})
    assert saved.status_code == 200
    assert saved.json() == {"ok": True, "name": "Ana"}

    read = client.get("/api/profile").json()
    assert read["exists"] is True
    assert read["name"] == "Ana"
    assert "vegetarian" in read["markdown"]


def test_profile_requires_a_string(client):
    response = client.put("/api/profile", json={})
    assert response.status_code == 400
    assert response.json() == {"error": "markdown (string) required"}


def test_internal_profile_mirrors_the_public_one(client):
    client.put("/api/profile", json={"markdown": "# Bo\n"})
    assert client.get("/internal/profile").json() == client.get("/api/profile").json()

    posted = client.post("/internal/profile", json={"markdown": "# Cy\n"})
    assert posted.status_code == 200
    assert posted.json() == {"ok": True, "name": "Cy"}


# --- settings --------------------------------------------------------------


def test_agent_setting_roundtrip_and_validation(client):
    assert client.get("/api/settings/agent").json() == {"agent": None}

    assert client.put("/api/settings/agent", json={"agent": "claude"}).json() == {
        "agent": "claude"
    }
    assert client.get("/api/settings/agent").json() == {"agent": "claude"}

    bad = client.put("/api/settings/agent", json={"agent": "bogus"})
    assert bad.status_code == 400
    assert bad.json() == {"error": "Unknown agent: bogus"}


def test_provider_setting_defaults_to_swiggy(client):
    assert client.get("/api/settings/provider").json() == {"provider": "swiggy-instamart"}

    assert client.put("/api/settings/provider", json={"provider": "zepto"}).json() == {
        "provider": "zepto"
    }

    bad = client.put("/api/settings/provider", json={"provider": "bogus"})
    assert bad.status_code == 400
    assert bad.json() == {"error": "Unknown provider: bogus"}


# --- sessions --------------------------------------------------------------


def test_current_session_payload_shape(client):
    payload = client.get("/api/session/current").json()
    assert set(payload) == {
        "sessionId",
        "agentSessionId",
        "name",
        "agent",
        "activeSurface",
        "profileExists",
        "messages",
    }
    assert payload["activeSurface"] == "chat"
    assert payload["messages"] == []
    assert payload["profileExists"] is False


def test_new_session_archives_the_previous_one(client):
    first = client.get("/api/session/current").json()["sessionId"]
    second = client.post("/api/session/new").json()["sessionId"]
    assert first != second

    listed = client.get("/api/sessions").json()["sessions"]
    statuses = {row["id"]: row["status"] for row in listed}
    assert statuses[first] == "ended"
    assert statuses[second] == "active"
    assert set(listed[0]) == {
        "id",
        "title",
        "name",
        "status",
        "created_at",
        "ended_at",
        "message_count",
    }


def test_surface_patch_validates(client):
    ok = client.patch("/api/session/surface", json={"activeSurface": "basket"})
    assert ok.status_code == 200
    assert ok.json()["activeSurface"] == "basket"

    bad = client.patch("/api/session/surface", json={"activeSurface": "bogus"})
    assert bad.status_code == 400
    assert bad.json() == {"error": "active surface must be chat, calendar, or basket"}


def test_internal_surface_shape(client):
    response = client.post("/internal/surface", json={"activeSurface": "chat"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "activeSurface": "chat"}


def test_messages_for_unknown_session_is_empty(client):
    assert client.get("/api/sessions/nope/messages").json() == {"messages": []}


def test_attachment_for_unknown_session_is_404(client):
    response = client.get("/api/sessions/nope/attachments/x.png")
    assert response.status_code == 404
    assert response.json() == {"error": "Session not found"}


# --- calendar --------------------------------------------------------------


def test_calendar_is_absent_until_written(client):
    assert client.get("/api/session/calendar").json() == {"exists": False, "calendar": None}


def test_internal_calendar_write_switches_surface(client):
    written = client.post("/internal/calendar", json=CALENDAR)
    assert written.status_code == 200
    body = written.json()
    assert body["ok"] is True
    assert body["calendar"]["ui"] == {"selectedWeekId": "week-1"}

    assert client.get("/api/session/calendar").json()["exists"] is True
    assert client.get("/api/session/current").json()["activeSurface"] == "calendar"
    assert client.get("/internal/calendar").json()["calendar"] == body["calendar"]


def test_calendar_patch_actions(client):
    client.post("/internal/calendar", json=CALENDAR)

    cleared = client.patch(
        "/api/session/calendar", json={"action": "clear_day", "weekId": "week-1", "day": "Monday"}
    )
    assert cleared.status_code == 200
    assert cleared.json()["calendar"]["weeks"][0]["days"][0] == {
        "day": "Monday",
        "disabled": True,
    }

    bad_action = client.patch("/api/session/calendar", json={"action": "bogus"})
    assert bad_action.status_code == 400
    assert bad_action.json() == {"error": "action must be clear_day or select_week"}

    missing_week = client.patch(
        "/api/session/calendar", json={"action": "select_week", "weekId": "nope"}
    )
    assert missing_week.status_code == 400
    assert missing_week.json() == {"error": 'Week "nope" was not found'}


def test_calendar_write_rejects_malformed_payload(client):
    response = client.post("/internal/calendar", json={"weeks": "not-an-array"})
    assert response.status_code == 400
    assert response.json() == {"error": "weeks must be an array"}


# --- basket ----------------------------------------------------------------


def test_basket_is_absent_until_written(client):
    assert client.get("/api/session/basket").json() == {"exists": False, "basket": None}
    assert client.get("/api/session/ingredient-list").json() == {"items": []}


def test_internal_basket_write_switches_surface(client):
    written = client.post("/internal/basket", json=BASKET)
    assert written.status_code == 200
    assert written.json()["ok"] is True
    assert written.json()["basket"]["items"][0]["count"] == 2

    assert client.get("/api/session/current").json()["activeSurface"] == "basket"


def test_basket_patch_actions(client):
    client.post("/internal/basket", json=BASKET)

    bumped = client.patch(
        "/api/session/basket", json={"action": "set_count", "ingredient": "Tomato", "count": 5}
    )
    assert bumped.json()["basket"]["items"][0]["count"] == 5

    removed = client.patch("/api/session/basket", json={"action": "remove", "ingredient": "Tomato"})
    assert removed.json()["basket"]["items"] == []

    bad = client.patch("/api/session/basket", json={"action": "bogus"})
    assert bad.status_code == 400
    assert bad.json() == {"error": "action must be set_count or remove"}


# --- tools + remote MCP metadata -------------------------------------------


def test_tools_lists_only_the_local_boppai_server(client):
    body = client.get("/api/tools").json()
    assert [server["name"] for server in body["servers"]] == ["boppai"]

    names = [tool["name"] for tool in body["servers"][0]["tools"]]
    assert names == [
        "get_profile",
        "save_profile",
        "show_chat",
        "show_calendar",
        "show_basket",
        "start_prava_checkout",
        "get_prava_checkout_credential",
        "report_prava_merchant_outcome",
        # Razorpay test mode -- the free rail added alongside the hackathon's Prava.
        "start_razorpay_checkout",
        "get_razorpay_payment_status",
    ]
    assert all(tool["description"] for tool in body["servers"][0]["tools"])


def test_remote_mcp_listing_is_metadata_only(client):
    body = client.get("/api/mcp/remote").json()
    assert [server["name"] for server in body["servers"]] == ["zepto", "swiggy-instamart"]
    # Remotes are streamable HTTP now; the agent CLI owns the OAuth, so the login hint
    # is a CLI command rather than the old `npx mcp-remote` bridge.
    assert body["servers"][0]["login"] == (
        "claude mcp add --transport http --scope user zepto https://mcp.zepto.co.in/mcp"
        " && claude mcp login zepto"
    )
    assert set(body["servers"][0]) == {"name", "label", "description", "login"}


def test_unknown_remote_mcp_is_404(client):
    response = client.get("/api/mcp/remote/nope/tools")
    assert response.status_code == 404
    assert response.json() == {"error": "Unknown remote MCP: nope"}


# --- detect ----------------------------------------------------------------


def test_detect_shape(client):
    body = client.get("/api/detect").json()
    agents = {agent["id"]: agent for agent in body["agents"]}
    assert set(agents) == {"claude", "codex"}
    for agent in agents.values():
        assert set(agent) == {
            "id",
            "name",
            "tagline",
            "bin",
            "supportsImages",
            "installed",
            "loggedIn",
            "account",
            "version",
        }
        assert isinstance(agent["installed"], bool)
        assert isinstance(agent["loggedIn"], bool)
