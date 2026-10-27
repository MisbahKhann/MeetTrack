"""HTTP client for the MeetTrack backend.

All backend calls go through this class so the Streamlit pages never
construct URLs or handle connection errors themselves.
"""

from __future__ import annotations

import os
from typing import Any

import requests


class ApiError(Exception):
    """Exception raised when an API call fails."""

    def __init__(self, message: str, status_code: int | None = None, detail: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or message


class ApiClient:
    """Wrapper around the MeetTrack backend REST API."""

    def __init__(self, base_url: str | None = None, timeout: int | None = None) -> None:
        self.base_url: str = (
            base_url or os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
        ).rstrip("/")
        default_timeout = int(os.environ.get("BACKEND_TIMEOUT", "120"))
        self.timeout: int = timeout if timeout is not None else default_timeout

    def _url(self, path: str) -> str:
        clean_path = path.lstrip("/")
        return f"{self.base_url}/api/v1/{clean_path}"

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", self.timeout)
        try:
            response = requests.request(method, url, **kwargs)
        except requests.exceptions.RequestException as exc:
            msg = "Backend unreachable. Please ensure the backend is running."
            raise ApiError(
                msg,
                status_code=503,
                detail=msg,
            ) from exc
        return self._handle_response(response)

    def _handle_response(self, response: requests.Response) -> Any:
        try:
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.content
        except requests.exceptions.HTTPError as exc:
            detail: str = ""
            try:
                body = response.json()
                detail = body.get("detail", str(exc))
            except Exception:
                detail = response.text or str(exc)
            raise ApiError(detail, status_code=response.status_code, detail=detail) from exc
        except requests.exceptions.RequestException as exc:
            raise ApiError("Backend unreachable. Please ensure the backend is running.", detail=str(exc)) from exc

    def health(self) -> dict[str, Any] | None:
        """Call GET /health. Returns the JSON body or None on any error."""
        try:
            res = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            res.raise_for_status()
            return res.json()
        except requests.exceptions.RequestException:
            return None

    # -----------------------------------------------------------------------
    # Teams
    # -----------------------------------------------------------------------

    def list_teams(self) -> list[dict[str, Any]]:
        """List all teams."""
        return self._request("GET", self._url("teams"))

    def create_team(
        self,
        name: str,
        members: list[str] | None = None,
        supervisor: str | None = None,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new team."""
        payload: dict[str, Any] = {
            "name": name,
            "members": members or [],
            "supervisor": supervisor,
        }
        if team_id:
            payload["team_id"] = team_id
        return self._request("POST", self._url("teams"), json=payload)

    def get_team(self, team_id: str) -> dict[str, Any]:
        """Get team by ID."""
        return self._request("GET", self._url(f"teams/{team_id}"))

    def add_member(self, team_id: str, name: str, email: str | None = None) -> dict[str, Any]:
        """Add member to team."""
        payload = {"name": name, "email": email}
        return self._request("POST", self._url(f"teams/{team_id}/members"), json=payload)

    def list_members(self, team_id: str) -> list[dict[str, Any]]:
        """List members of a team."""
        return self._request("GET", self._url(f"teams/{team_id}/members"))

    def delete_team(self, team_id: str) -> None:
        """Delete a team and its associated records."""
        self._request("DELETE", self._url(f"teams/{team_id}"))

    # -----------------------------------------------------------------------
    # Meetings
    # -----------------------------------------------------------------------

    def ingest_notes(
        self,
        team_id: str,
        file_name: str,
        content: str,
        as_of: str | None = None,
        memory_enabled: bool = True,
    ) -> dict[str, Any]:
        """Ingest meeting notes and run cycle."""
        payload = {
            "team_id": team_id,
            "file_name": file_name,
            "content": content,
            "as_of": as_of,
            "memory_enabled": memory_enabled,
        }
        return self._request("POST", self._url("meetings/ingest"), json=payload)

    def list_meetings(self, team_id: str) -> list[dict[str, Any]]:
        """List meetings for a team."""
        return self._request("GET", self._url("meetings"), params={"team_id": team_id})

    # -----------------------------------------------------------------------
    # Proposals
    # -----------------------------------------------------------------------

    def list_proposals(self, team_id: str, cycle_id: str) -> list[dict[str, Any]]:
        """List proposals for a cycle."""
        return self._request("GET", self._url("proposals"), params={"team_id": team_id, "cycle_id": cycle_id})

    def decide_proposal(
        self,
        team_id: str,
        proposal_id: str,
        decision: str,
        user_comment: str | None = None,
        edited_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Decide (approve, edit, reject) on a proposal."""
        payload = {
            "team_id": team_id,
            "decision": decision,
            "user_comment": user_comment,
            "edited_payload": edited_payload,
        }
        return self._request("POST", self._url(f"proposals/{proposal_id}/decide"), json=payload)

    def commit_proposals(self, team_id: str, cycle_id: str) -> list[dict[str, Any]]:
        """Commit approved proposals in a cycle."""
        payload = {"team_id": team_id, "cycle_id": cycle_id}
        return self._request("POST", self._url("proposals/commit"), json=payload)

    # -----------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------

    def list_actions(self, team_id: str, include_done: bool = True) -> list[dict[str, Any]]:
        """List actions for a team."""
        return self._request("GET", self._url("actions"), params={"team_id": team_id, "include_done": str(include_done).lower()})

    def get_action_history(self, team_id: str, action_id: str) -> list[dict[str, Any]]:
        """Retrieve version history for an action."""
        return self._request("GET", self._url(f"actions/{action_id}/history"), params={"team_id": team_id})

    def correct_action(
        self,
        team_id: str,
        action_id: str,
        field: str,
        value: Any,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Apply a correction to an action."""
        payload = {
            "team_id": team_id,
            "field": field,
            "value": value,
            "comment": comment,
        }
        return self._request("POST", self._url(f"actions/{action_id}/correct"), json=payload)

    # -----------------------------------------------------------------------
    # Exports & Reminders
    # -----------------------------------------------------------------------

    def download_register(self, team_id: str, as_of: str | None = None) -> bytes:
        """Download Excel action register bytes."""
        params = {"team_id": team_id}
        if as_of:
            params["as_of"] = as_of
        return self._request("GET", self._url("exports/register"), params=params)

    def list_reminders(self, team_id: str, cycle_id: str | None = None) -> list[dict[str, Any]]:
        """List UNSENT reminder drafts."""
        params = {"team_id": team_id}
        if cycle_id:
            params["cycle_id"] = cycle_id
        return self._request("GET", self._url("exports/reminders"), params=params)

    def generate_reminders(self, team_id: str, cycle_id: str, as_of: str | None = None) -> list[dict[str, Any]]:
        """Generate reminder drafts for a cycle."""
        payload = {
            "team_id": team_id,
            "cycle_id": cycle_id,
            "as_of": as_of,
        }
        return self._request("POST", self._url("exports/reminders/generate"), json=payload)
