"""An in-memory notes API with the same shape as api-hono-starter's, for fast tests."""

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


class FakeNotesApi:
    def __init__(self, token: str) -> None:
        self.token = token
        self.notes: list[dict[str, Any]] = []
        self.requests: list[Request] = []
        self.next_response: Response | None = None
        self.app = Starlette(routes=[Route("/v1/notes", self._notes, methods=["GET", "POST"])])

    def add(self, title: str, body: str = "") -> dict[str, Any]:
        note = {
            "id": f"note_{len(self.notes) + 1:04d}",
            "title": title,
            "body": body,
            "createdAt": "2026-11-08T12:00:00.000Z",
        }
        self.notes.insert(0, note)
        return note

    async def _notes(self, request: Request) -> Response:
        self.requests.append(request)
        if self.next_response is not None:
            response, self.next_response = self.next_response, None
            return response
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return JSONResponse({"type": "urn:problem:unauthorized"}, status_code=401)
        if request.method == "POST":
            payload = await request.json()
            return JSONResponse(self.add(payload["title"], payload["body"]), status_code=201)
        limit = int(request.query_params.get("limit", "20"))
        cursor = request.query_params.get("cursor")
        start = next((i + 1 for i, n in enumerate(self.notes) if n["id"] == cursor), 0)
        page = self.notes[start : start + limit]
        more = start + limit < len(self.notes)
        return JSONResponse(
            {"data": page, "meta": {"limit": limit, "nextCursor": page[-1]["id"] if more else None}}
        )
