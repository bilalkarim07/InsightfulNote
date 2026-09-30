"""Offline contract check for Threads publishing auth and request payloads."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from sources.threads.api import ThreadsAPI  # noqa: E402
from sources.threads.models import ThreadsToken  # noqa: E402


class FixedTokenStore:
    def __init__(self) -> None:
        self.token = ThreadsToken(
            access_token="test-access-token",
            user_id="123456",
        )

    def load(self) -> ThreadsToken:
        return self.token

    def save(self, token: ThreadsToken) -> None:
        self.token = token


def main() -> int:
    requests: list[tuple[str, str, dict[str, Any] | None, str | None]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        requests.append((
            request.method,
            request.url.path,
            payload,
            request.headers.get("Authorization"),
        ))
        if request.url.path.endswith("/123456/threads"):
            return httpx.Response(200, json={"id": "container-1"})
        if request.url.path.endswith("/123456/threads_publish"):
            return httpx.Response(200, json={"id": "published-1"})
        return httpx.Response(404, json={"error": {"message": "unexpected path"}})

    api = ThreadsAPI(
        app_id="test-app",
        app_secret="test-secret",
        token_store=FixedTokenStore(),
    )
    api._client._http.close()
    api._client._http = httpx.Client(transport=httpx.MockTransport(respond))
    try:
        result = api.create_post(text="offline contract test")
    finally:
        api.close()

    expected_paths = [
        "/v1.0/123456/threads",
        "/v1.0/123456/threads_publish",
    ]
    assert [request[1] for request in requests] == expected_paths
    assert all(
        request[3] == "Bearer test-access-token"
        for request in requests
    ), "Threads requests must use the configured bearer token"
    assert requests[0][2] == {
        "media_type": "TEXT",
        "text": "offline contract test",
    }
    assert requests[1][2] == {"creation_id": "container-1"}
    assert result == {"id": "published-1"}

    print("[PASS] Threads publish flow uses bearer auth and expected two-step payload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
