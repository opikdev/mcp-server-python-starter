import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
SERVER = json.loads((ROOT / "server.json").read_text())
SECRET = re.compile(r"(TOKEN|TOKENS|SECRET)$")


def package(registry_type: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        entry for entry in SERVER["packages"] if entry["registryType"] == registry_type
    )
    return found


def test_keeps_server_json_in_step_with_pyproject() -> None:
    pypi = package("pypi")
    assert [entry["registryType"] for entry in SERVER["packages"]] == ["pypi", "oci"]
    assert SERVER["version"] == PROJECT["version"] == pypi["version"]
    assert pypi["identifier"] == PROJECT["name"]
    assert pypi["transport"] == {"type": "stdio"}
    assert SERVER["description"] == PROJECT["description"]


def test_lists_the_ghcr_image_at_the_release_version_served_over_http() -> None:
    repository = SERVER["name"].removeprefix("io.github.")
    oci = package("oci")
    assert oci["identifier"] == f"ghcr.io/{repository}:{PROJECT['version']}"
    assert oci["transport"]["type"] == "streamable-http"
    assert "version" not in oci


def test_labels_the_image_with_the_server_name_so_the_registry_can_verify_it() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert f'LABEL io.modelcontextprotocol.server.name="{SERVER["name"]}"' in dockerfile


@pytest.mark.parametrize("registry_type", ["pypi", "oci"])
def test_describes_every_setting_and_marks_secrets(registry_type: str) -> None:
    variables = package(registry_type)["environmentVariables"]
    names = [variable["name"] for variable in variables]
    assert {"UPSTREAM_API_URL", "UPSTREAM_API_TOKEN", "UPSTREAM_TIMEOUT_MS"} <= set(names)
    for variable in variables:
        assert variable["description"], variable["name"]
        assert variable.get("isSecret", False) == bool(SECRET.search(variable["name"]))


def test_lists_the_auth_and_token_exchange_settings_for_the_http_image() -> None:
    names = {variable["name"] for variable in package("oci")["environmentVariables"]}
    assert {
        "MCP_AUTH_MODE",
        "MCP_AUTH_TOKENS",
        "MCP_AUTH_ISSUER",
        "MCP_PUBLIC_URL",
        "UPSTREAM_AUTH",
        "UPSTREAM_AUDIENCE",
        "TOKEN_EXCHANGE_URL",
        "TOKEN_EXCHANGE_CLIENT_ID",
        "TOKEN_EXCHANGE_CLIENT_SECRET",
    } <= names


def test_adds_no_remotes_until_the_server_is_hosted() -> None:
    assert "remotes" not in SERVER


def test_proves_registry_ownership_in_the_readme() -> None:
    assert f"<!-- mcp-name: {SERVER['name']} -->" in (ROOT / "README.md").read_text()
