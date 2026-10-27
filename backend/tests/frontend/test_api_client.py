"""Focused tests for the frontend ApiClient."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from api_client import ApiClient, ApiError


@pytest.fixture()
def client() -> ApiClient:
    return ApiClient(base_url="http://testserver:8000")


def test_api_client_health(client: ApiClient) -> None:
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "service": "meettrack-backend"}
        mock_get.return_value = mock_resp

        res = client.health()
        assert res is not None
        assert res["status"] == "ok"
        mock_get.assert_called_once_with("http://testserver:8000/health", timeout=15)


def test_api_client_team_lifecycle(client: ApiClient) -> None:
    with patch("requests.request") as mock_req:
        # Create team
        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 201
        mock_post_resp.headers = {"content-type": "application/json"}
        mock_post_resp.json.return_value = {"team_id": "t-1", "name": "Team 1", "supervisor": "Dr. Smith"}
        mock_req.return_value = mock_post_resp

        created = client.create_team(name="Team 1", members=["Alice", "Bob"], supervisor="Dr. Smith")
        assert created["team_id"] == "t-1"
        assert created["name"] == "Team 1"

        # List teams
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.headers = {"content-type": "application/json"}
        mock_get_resp.json.return_value = [created]
        mock_req.return_value = mock_get_resp

        teams = client.list_teams()
        assert len(teams) == 1
        assert teams[0]["name"] == "Team 1"


def test_api_client_ingest_notes(client: ApiClient) -> None:
    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {
            "status": "proposed",
            "cycle_id": "cyc-1",
            "meeting_id": "mtg-1",
            "as_of": "2026-01-15",
            "proposals": [],
            "warnings": [],
            "llm_calls": 1,
        }
        mock_req.return_value = mock_resp

        report = client.ingest_notes(
            team_id="t-1",
            file_name="notes.txt",
            content="1. Alice will do tasks.",
            as_of="2026-01-15",
            memory_enabled=True,
        )
        assert report["status"] == "proposed"
        assert report["cycle_id"] == "cyc-1"


def test_api_client_proposals_decide_and_commit(client: ApiClient) -> None:
    with patch("requests.request") as mock_req:
        # Decide
        mock_resp_dec = MagicMock()
        mock_resp_dec.status_code = 200
        mock_resp_dec.headers = {"content-type": "application/json"}
        mock_resp_dec.json.return_value = {
            "decision_id": "dec-1",
            "proposal_id": "p-1",
            "team_id": "t-1",
            "decision": "approve",
        }
        mock_req.return_value = mock_resp_dec

        dec = client.decide_proposal(team_id="t-1", proposal_id="p-1", decision="approve")
        assert dec["decision"] == "approve"

        # Commit
        mock_resp_com = MagicMock()
        mock_resp_com.status_code = 200
        mock_resp_com.headers = {"content-type": "application/json"}
        mock_resp_com.json.return_value = [{"proposal_id": "p-1", "outcome": "new_action", "already_committed": False}]
        mock_req.return_value = mock_resp_com

        committed = client.commit_proposals(team_id="t-1", cycle_id="cyc-1")
        assert len(committed) == 1
        assert committed[0]["outcome"] == "new_action"


def test_api_client_exports_and_reminders(client: ApiClient) -> None:
    with patch("requests.request") as mock_req:
        # Download register (bytes)
        mock_resp_bytes = MagicMock()
        mock_resp_bytes.status_code = 200
        mock_resp_bytes.headers = {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
        mock_resp_bytes.content = b"fake-excel-data"
        mock_req.return_value = mock_resp_bytes

        data = client.download_register(team_id="t-1")
        assert data == b"fake-excel-data"

        # List reminders (JSON)
        mock_resp_rem = MagicMock()
        mock_resp_rem.status_code = 200
        mock_resp_rem.headers = {"content-type": "application/json"}
        mock_resp_rem.json.return_value = [
            {
                "reminder_id": "rem-1",
                "team_id": "t-1",
                "action_id": "act-1",
                "recipient_name": "Alice",
                "draft_text": "STATUS: UNSENT",
                "status": "UNSENT",
            }
        ]
        mock_req.return_value = mock_resp_rem

        reminders = client.list_reminders(team_id="t-1")
        assert len(reminders) == 1
        assert reminders[0]["status"] == "UNSENT"


def test_api_client_error_handling(client: ApiClient) -> None:
    with patch("requests.request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {"detail": "Team 't-999' not found"}
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Client Error")
        mock_req.return_value = mock_resp

        with pytest.raises(ApiError) as exc_info:
            client.get_team("t-999")
        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    # Connection error handling
    with patch("requests.request", side_effect=requests.exceptions.ConnectionError("Connection refused")):
        with pytest.raises(ApiError) as exc_info:
            client.list_teams()
        assert "unreachable" in exc_info.value.detail.lower()
