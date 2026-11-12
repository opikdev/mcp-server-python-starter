"""Errors from backend calls, written for the model to read."""

import json
import unicodedata

MAX_DETAIL_LENGTH = 500


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


def quote_untrusted(text: str) -> str:
    """Quotes text from a backend as data, capped and without control or formatting characters.

    A backend's error message can carry anything, including text that reads like instructions,
    so the model gets it as a JSON string it can't break out of.
    """
    printable = "".join(
        " " if unicodedata.category(char) in ("Cc", "Cf", "Zl", "Zp") else char for char in text
    )
    collapsed = " ".join(printable.split())
    if len(collapsed) > MAX_DETAIL_LENGTH:
        collapsed = f"{collapsed[: MAX_DETAIL_LENGTH - 1]}…"
    return json.dumps(collapsed, ensure_ascii=False)
