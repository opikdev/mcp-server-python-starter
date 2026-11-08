import pytest

from mcp_app.config import (
    ConfigError,
    NoAuthConfig,
    OAuthConfig,
    TokenConfig,
    load_http_config,
    load_log_level,
    load_upstream_config,
)

TOKEN = "a-long-enough-token"


def test_refuses_to_start_without_an_auth_mode() -> None:
    with pytest.raises(ConfigError, match="Set MCP_AUTH_MODE to oauth, token, or none"):
        load_http_config({})


def test_defaults_to_a_localhost_bind_and_url() -> None:
    config = load_http_config({"MCP_AUTH_MODE": "token", "MCP_AUTH_TOKENS": TOKEN})
    assert (config.host, config.port, config.public_url, config.path) == (
        "127.0.0.1",
        3000,
        "http://localhost:3000/mcp",
        "/mcp",
    )
    assert config.allowed_hosts == ["localhost", "127.0.0.1", "[::1]"]
    assert config.auth == TokenConfig(tokens=[TOKEN], scopes=["mcp"])


def test_allows_the_public_url_host_and_custom_scopes() -> None:
    config = load_http_config(
        {
            "MCP_AUTH_MODE": "oauth",
            "MCP_AUTH_ISSUER": "https://auth.example.com/",
            "MCP_PUBLIC_URL": "https://mcp.example.com/tools/mcp",
            "MCP_AUTH_SCOPES": "mcp  notes:read",
        }
    )
    assert config.allowed_hosts[-1] == "mcp.example.com"
    assert config.path == "/tools/mcp"
    assert config.auth == OAuthConfig(
        issuer="https://auth.example.com", jwks_url=None, scopes=["mcp", "notes:read"]
    )


def test_treats_empty_variables_as_unset() -> None:
    config = load_http_config(
        {"MCP_AUTH_MODE": "token", "MCP_AUTH_TOKENS": TOKEN, "MCP_PUBLIC_URL": "", "PORT": ""}
    )
    assert config.public_url == "http://localhost:3000/mcp"
    with pytest.raises(ConfigError, match="Set MCP_AUTH_MODE"):
        load_http_config({"MCP_AUTH_MODE": ""})


def test_uses_explicit_allowed_hosts_as_given() -> None:
    config = load_http_config(
        {"MCP_AUTH_MODE": "token", "MCP_AUTH_TOKENS": TOKEN, "MCP_ALLOWED_HOSTS": "a.test, b.test"}
    )
    assert config.allowed_hosts == ["a.test", "b.test"]


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"MCP_AUTH_MODE": "oauth"}, "needs MCP_AUTH_ISSUER"),
        ({"MCP_AUTH_MODE": "token"}, "needs MCP_AUTH_TOKENS"),
        ({"MCP_AUTH_MODE": "token", "MCP_AUTH_TOKENS": "short"}, "at least 16 characters"),
        ({"MCP_AUTH_MODE": "none", "HOST": "0.0.0.0"}, "only allowed when HOST is a loopback"),
        ({"MCP_AUTH_MODE": "magic"}, "MCP_AUTH_MODE"),
        ({"MCP_AUTH_MODE": "none", "PORT": "70000"}, "PORT"),
    ],
)
def test_explains_each_invalid_setting(env: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_http_config(env)


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost"])
def test_allows_no_auth_on_every_loopback_host(host: str) -> None:
    assert load_http_config({"MCP_AUTH_MODE": "none", "HOST": host}).auth == NoAuthConfig()


def test_never_echoes_a_secret_in_an_error() -> None:
    secret = "super-secret-value-123"
    with pytest.raises(ConfigError) as error:
        load_upstream_config({"UPSTREAM_API_URL": secret, "UPSTREAM_API_TOKEN": secret})
    assert secret not in str(error.value)
    assert "UPSTREAM_API_URL" in str(error.value)


def test_upstream_is_off_by_default() -> None:
    assert load_upstream_config({}) is None


def test_reads_the_upstream_api_token_and_timeout() -> None:
    config = load_upstream_config(
        {
            "UPSTREAM_API_URL": "http://localhost:3200",
            "UPSTREAM_API_TOKEN": "t",
            "UPSTREAM_TIMEOUT_MS": "1500",
        }
    )
    assert config is not None
    assert (config.base_url, config.token, config.timeout_seconds) == (
        "http://localhost:3200/",
        "t",
        1.5,
    )


def test_requires_a_token_when_the_api_is_set() -> None:
    with pytest.raises(ConfigError, match="UPSTREAM_API_TOKEN is required"):
        load_upstream_config({"UPSTREAM_API_URL": "http://localhost:3200"})


def test_reads_the_log_level() -> None:
    assert load_log_level({"LOG_LEVEL": "DEBUG".lower()}) == "debug"
    assert load_log_level({}) == "info"
