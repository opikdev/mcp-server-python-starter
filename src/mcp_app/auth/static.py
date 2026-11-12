"""Static bearer tokens, for internal services and local development."""

import hashlib
import hmac

from mcp.server.auth.provider import AccessToken


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


class StaticTokenVerifier:
    """Accepts any of the configured tokens, comparing digests in constant time.

    A static token has no scopes of its own, so pass every scope the server uses.
    """

    def __init__(self, tokens: list[str], scopes: list[str]) -> None:
        self._digests = [_digest(token) for token in tokens]
        self._scopes = list(dict.fromkeys(scopes))

    async def verify_token(self, token: str) -> AccessToken | None:
        actual = _digest(token)
        matches = [hmac.compare_digest(expected, actual) for expected in self._digests]
        if not any(matches):
            return None
        return AccessToken(
            token=token, client_id=f"token-{matches.index(True) + 1}", scopes=self._scopes
        )
