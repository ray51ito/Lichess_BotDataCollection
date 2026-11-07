"""Thin, rate-limit-aware client for the public Lichess API endpoints used by the study."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import httpx

API_ROOT: str = "https://lichess.org/api"
"""Base URL of the Lichess API."""

USERS_BATCH: int = 300
"""Maximum usernames per ``POST /api/users`` request."""

USER_AGENT: str = "lichess-ai-pref research (revealed preference for chess bots)"
"""User agent sent with every request."""


class LichessApi:
    """Sequential client that waits between requests and backs off on HTTP 429.

    Lichess asks clients to send one request at a time and to wait a full minute after a 429.
    """

    def __init__(self, client: httpx.Client | None = None, pause_s: float = 1.0) -> None:
        """Creates a client.

        Args:
            client: HTTP client to use (a default one is created when None).
            pause_s: Delay after every request.
        """
        self._client = client or httpx.Client(
            timeout=60, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._pause_s = pause_s

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response | None:
        # returns None for 404 (closed or unknown accounts)
        for attempt in range(6):
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.TransportError:
                # dropped connections happen on long runs: wait and retry
                time.sleep(30 * (attempt + 1))
                continue
            time.sleep(self._pause_s)
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                time.sleep(60 * (attempt + 1))
                continue
            if response.status_code == httpx.codes.NOT_FOUND:
                return None
            response.raise_for_status()
            return response
        raise RuntimeError(f"Lichess API kept rate limiting {url}")

    def users(self, names: Sequence[str]) -> list[dict[str, Any]]:
        """Returns public profiles of up to ``USERS_BATCH`` users (missing ones are omitted)."""
        response = self._request(
            "POST",
            f"{API_ROOT}/users",
            content=",".join(names),
            headers={"Content-Type": "text/plain"},
        )
        users: list[dict[str, Any]] = response.json() if response is not None else []
        return users

    def user(self, name: str) -> dict[str, Any] | None:
        """Returns one user's full public profile (includes game counts); None if gone."""
        response = self._request("GET", f"{API_ROOT}/user/{name}")
        user: dict[str, Any] | None = response.json() if response is not None else None
        return user

    def rating_history(self, name: str) -> list[dict[str, Any]]:
        """Returns the per-speed rating history of a user (empty if the account is gone)."""
        response = self._request("GET", f"{API_ROOT}/user/{name}/rating-history")
        history: list[dict[str, Any]] = response.json() if response is not None else []
        return history

    def online_bots(self, limit: int = 300) -> list[dict[str, Any]]:
        """Returns the bots currently online, in the order Lichess lists them."""
        response = self._request("GET", f"{API_ROOT}/bot/online", params={"nb": limit})
        if response is None:
            return []
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]
