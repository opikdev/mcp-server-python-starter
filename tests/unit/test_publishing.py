import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_keeps_server_json_in_step_with_pyproject() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    server = json.loads((ROOT / "server.json").read_text())
    package = server["packages"][0]
    assert server["version"] == project["version"] == package["version"]
    assert package["identifier"] == project["name"]
    assert server["description"] == project["description"]


def test_proves_registry_ownership_in_the_readme() -> None:
    server = json.loads((ROOT / "server.json").read_text())
    assert f"<!-- mcp-name: {server['name']} -->" in (ROOT / "README.md").read_text()
