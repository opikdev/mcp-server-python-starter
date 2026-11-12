"""Settings from environment variables, validated once at startup."""

import ipaddress
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["debug", "info", "warning", "error"]

MIN_TOKEN_LENGTH = 16
LOCALHOST_NAMES = ("localhost", "127.0.0.1", "[::1]")


class ConfigError(Exception):
    """A setting is missing or invalid. The message names the variable and how to fix it."""


class _Env(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False, env_ignore_empty=True)

    log_level: LogLevel = "info"
    host: str = "127.0.0.1"
    port: int = Field(default=3000, ge=1, le=65535)
    mcp_public_url: AnyHttpUrl | None = None
    mcp_allowed_hosts: str = ""
    mcp_auth_mode: Literal["oauth", "token", "none"] | None = None
    mcp_auth_tokens: str = ""
    mcp_auth_issuer: AnyHttpUrl | None = None
    mcp_auth_jwks_url: AnyHttpUrl | None = None
    mcp_auth_scopes: str = "mcp"
    upstream_api_url: AnyHttpUrl | None = None
    upstream_api_token: str | None = None
    upstream_timeout_ms: int = Field(default=5000, ge=100, le=60_000)
    upstream_auth: Literal["static", "exchange"] = "static"
    upstream_audience: str | None = None
    token_exchange_url: AnyHttpUrl | None = None
    token_exchange_client_id: str | None = None
    token_exchange_client_secret: str | None = None
    shutdown_drain_seconds: int = Field(default=5, ge=0, le=300)
    shutdown_timeout_seconds: int = Field(default=30, ge=1, le=600)


@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    jwks_url: str | None
    scopes: list[str]
    mode: Literal["oauth"] = "oauth"


@dataclass(frozen=True)
class TokenConfig:
    tokens: list[str]
    scopes: list[str]
    mode: Literal["token"] = "token"


@dataclass(frozen=True)
class NoAuthConfig:
    mode: Literal["none"] = "none"


AuthConfig = OAuthConfig | TokenConfig | NoAuthConfig


@dataclass(frozen=True)
class HttpConfig:
    host: str
    port: int
    public_url: str
    allowed_hosts: list[str]
    auth: AuthConfig
    shutdown_drain_seconds: int = 5
    shutdown_timeout_seconds: int = 30

    @property
    def path(self) -> str:
        return urlsplit(self.public_url).path or "/mcp"


@dataclass(frozen=True)
class StaticCredentialsConfig:
    token: str
    mode: Literal["static"] = "static"


@dataclass(frozen=True)
class ExchangeCredentialsConfig:
    token_url: str
    client_id: str
    client_secret: str = field(repr=False)
    audience: str
    mode: Literal["exchange"] = "exchange"


@dataclass(frozen=True)
class UpstreamConfig:
    base_url: str
    timeout_seconds: float
    credentials: StaticCredentialsConfig | ExchangeCredentialsConfig


def _parse(env: dict[str, str] | None) -> _Env:
    try:
        if env is None:
            return _Env()
        # Treat an empty variable as unset, as the environment source does.
        return _Env.model_validate({key.lower(): value for key, value in env.items() if value})
    except ValidationError as error:
        # Name each variable and the problem, but never echo the value: it may be a secret.
        fields = [
            f"{'.'.join(str(part) for part in issue['loc']).upper()}: {issue['msg']}"
            for issue in error.errors(include_input=False, include_url=False)
        ]
        raise ConfigError(f"Invalid environment: {'; '.join(fields)}") from None


def _split(value: str, separator: str | None = ",") -> list[str]:
    return [item.strip() for item in value.split(separator) if item.strip()]


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def load_log_level(env: dict[str, str] | None = None) -> LogLevel:
    return _parse(env).log_level


def _require_https(name: str, url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" and not _is_loopback(parts.hostname or ""):
        raise ConfigError(f"{name} must use https://, except on a loopback host, not {url}.")


def _exchange(data: _Env) -> ExchangeCredentialsConfig:
    if data.mcp_auth_mode != "oauth":
        raise ConfigError(
            "UPSTREAM_AUTH=exchange needs MCP_AUTH_MODE=oauth, because it exchanges the caller's "
            "OAuth access token."
        )
    url, client_id, secret, audience = (
        data.token_exchange_url,
        data.token_exchange_client_id,
        data.token_exchange_client_secret,
        data.upstream_audience,
    )
    if url is None or not client_id or not secret or not audience:
        missing = [
            name
            for name, value in (
                ("TOKEN_EXCHANGE_URL", url),
                ("TOKEN_EXCHANGE_CLIENT_ID", client_id),
                ("TOKEN_EXCHANGE_CLIENT_SECRET", secret),
                ("UPSTREAM_AUDIENCE", audience),
            )
            if not value
        ]
        raise ConfigError(f"UPSTREAM_AUTH=exchange needs {', '.join(missing)}.")
    _require_https("TOKEN_EXCHANGE_URL", str(url))
    return ExchangeCredentialsConfig(
        token_url=str(url), client_id=client_id, client_secret=secret, audience=audience
    )


def load_upstream_config(env: dict[str, str] | None = None) -> UpstreamConfig | None:
    data = _parse(env)
    if data.upstream_api_url is None:
        return None
    credentials: StaticCredentialsConfig | ExchangeCredentialsConfig
    if data.upstream_auth == "exchange":
        credentials = _exchange(data)
    elif data.upstream_api_token:
        credentials = StaticCredentialsConfig(token=data.upstream_api_token)
    else:
        raise ConfigError("UPSTREAM_API_URL is set, so UPSTREAM_API_TOKEN is required too.")
    return UpstreamConfig(
        base_url=str(data.upstream_api_url),
        timeout_seconds=data.upstream_timeout_ms / 1000,
        credentials=credentials,
    )


def _auth(data: _Env) -> AuthConfig:
    scopes = _split(data.mcp_auth_scopes, None)
    match data.mcp_auth_mode:
        case "oauth":
            if data.mcp_auth_issuer is None:
                raise ConfigError(
                    "MCP_AUTH_MODE=oauth needs MCP_AUTH_ISSUER, the authorization server URL."
                )
            issuer = str(data.mcp_auth_issuer).removesuffix("/")
            jwks = str(data.mcp_auth_jwks_url) if data.mcp_auth_jwks_url else None
            _require_https("MCP_AUTH_ISSUER", issuer)
            if jwks is not None:
                _require_https("MCP_AUTH_JWKS_URL", jwks)
            return OAuthConfig(issuer=issuer, jwks_url=jwks, scopes=scopes)
        case "token":
            tokens = _split(data.mcp_auth_tokens)
            if not tokens:
                raise ConfigError(
                    "MCP_AUTH_MODE=token needs MCP_AUTH_TOKENS, a comma-separated list of tokens."
                )
            if any(len(token) < MIN_TOKEN_LENGTH for token in tokens):
                raise ConfigError(
                    f"Every token in MCP_AUTH_TOKENS must have at least {MIN_TOKEN_LENGTH} "
                    "characters."
                )
            return TokenConfig(tokens=tokens, scopes=scopes)
        case "none":
            if not _is_loopback(data.host):
                raise ConfigError(
                    "MCP_AUTH_MODE=none is only allowed when HOST is a loopback address, "
                    f"not {data.host}."
                )
            return NoAuthConfig()
        case None:
            raise ConfigError(
                "Set MCP_AUTH_MODE to oauth, token, or none before serving over HTTP. "
                "See docs/auth.md."
            )


def load_http_config(env: dict[str, str] | None = None) -> HttpConfig:
    data = _parse(env)
    public_url = str(data.mcp_public_url or f"http://localhost:{data.port}/mcp")
    allowed = _split(data.mcp_allowed_hosts) or list(
        dict.fromkeys([*LOCALHOST_NAMES, urlsplit(public_url).hostname or "localhost"])
    )
    auth = _auth(data)
    if isinstance(auth, OAuthConfig):
        _require_https("MCP_PUBLIC_URL", public_url)
    return HttpConfig(
        host=data.host,
        port=data.port,
        public_url=public_url,
        allowed_hosts=allowed,
        auth=auth,
        shutdown_drain_seconds=data.shutdown_drain_seconds,
        shutdown_timeout_seconds=data.shutdown_timeout_seconds,
    )
