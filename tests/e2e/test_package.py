"""Builds the wheel and runs it with uvx, as a client configured from the MCP Registry would."""

import subprocess
import zipfile
from pathlib import Path

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

ROOT = Path(__file__).parents[2]

pytestmark = pytest.mark.anyio


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(out)], cwd=ROOT, check=True)
    return next(out.glob("*.whl"))


def test_contains_only_the_server_package(wheel: Path) -> None:
    names = zipfile.ZipFile(wheel).namelist()
    assert {name.split("/")[0] for name in names} == {
        "mcp_app",
        f"{wheel.name.split('-py3')[0]}.dist-info",
    }
    assert "mcp_app/py.typed" in names


def test_prints_its_version(wheel: Path) -> None:
    result = subprocess.run(
        ["uvx", "--from", str(wheel), "mcp-server-python-starter", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "0.1.0"


async def test_serves_tools_over_stdio_from_its_script(wheel: Path) -> None:
    process = StdioServerParameters(
        command="uvx", args=["--from", str(wheel), "mcp-server-python-starter"]
    )
    async with Client(process) as client:
        result = await client.call_tool("search_docs", {"query": "tools"})
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["results"]
