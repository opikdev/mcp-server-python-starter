"""A client for a REST notes API, with a timeout, response validation, and model-friendly errors."""

from typing import Any

import httpx2
from pydantic import BaseModel, ValidationError

from mcp_app.models import CamelModel


class Note(CamelModel):
    id: str
    title: str
    body: str
    created_at: str


class _PageMeta(CamelModel):
    next_cursor: str | None


class NotePage(CamelModel):
    data: list[Note]
    meta: _PageMeta


class UpstreamError(Exception):
    """A failure written for the model, such as "Retry in 30 seconds". Never holds secrets."""

    def __init__(
        self, message: str, status: int | None = None, retry_after_seconds: int | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after_seconds = retry_after_seconds


class NoResponseError(UpstreamError):
    """The API didn't answer, so a write may or may not have happened."""


def _detail(response: httpx2.Response) -> str | None:
    try:
        detail = response.json().get("detail")
    except ValueError, AttributeError:
        return None
    return detail if isinstance(detail, str) else None


def _error(response: httpx2.Response) -> UpstreamError:
    status = response.status_code
    if status in (401, 403):
        return UpstreamError(
            "The notes API rejected this server's credentials. "
            "Ask the operator to check UPSTREAM_API_TOKEN.",
            status,
        )
    if status == 429:
        retry_after = response.headers.get("retry-after", "")
        seconds = int(retry_after) if retry_after.isdigit() and int(retry_after) > 0 else 60
        return UpstreamError(
            f"The notes API is rate limiting requests. Retry in {seconds} seconds.", 429, seconds
        )
    if 400 <= status < 500:
        detail = _detail(response) or f"HTTP {status}"
        return UpstreamError(f"The notes API refused the request: {detail}", status)
    return UpstreamError(f"The notes API failed with HTTP {status}. Try again later.", status)


class NotesClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._http = httpx2.AsyncClient(
            base_url=base_url if base_url.endswith("/") else f"{base_url}/",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request[T: BaseModel](
        self, method: str, path: str, model: type[T], **kwargs: Any
    ) -> T:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx2.TimeoutException:
            raise NoResponseError(
                f"The notes API didn't answer within {self._timeout:g} seconds. Try again later."
            ) from None
        except httpx2.TransportError:
            raise NoResponseError("Couldn't reach the notes API. Try again later.") from None
        if not response.is_success:
            raise _error(response)
        try:
            return model.model_validate_json(response.content)
        except ValidationError:
            raise UpstreamError(
                "The notes API sent a response this server doesn't understand."
            ) from None

    async def list(self, *, limit: int, cursor: str | None = None) -> NotePage:
        params: dict[str, str | int] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "v1/notes", NotePage, params=params)

    async def create(self, *, title: str, body: str) -> Note:
        return await self._request("POST", "v1/notes", Note, json={"title": title, "body": body})
