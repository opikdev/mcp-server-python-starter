# Publish a release

Pushing a `vX.Y.Z` tag runs `.github/workflows/release.yml`.

| Target | Runs when | Setup |
|---|---|---|
| Docker image on GHCR, for amd64 and arm64 | Always | None |
| PyPI package | The repo variable `PYPI_PUBLISH` is `true` | Add a trusted publisher on PyPI for this repo, the `release.yml` workflow, and the `pypi` environment |
| MCP Registry | The repo variable `MCP_REGISTRY_PUBLISH` is `true` | PyPI publishing must work first, because the registry checks the `mcp-name` comment in the package README |

## Release

1. Bump `version` in `pyproject.toml`, and both `version` fields in `server.json`, then run `uv lock`.
2. Add the release to `CHANGELOG.md`.
3. Run `make verify` and `make e2e`.
4. Merge the change through a pull request, because `main` only accepts pull requests.
5. Tag the merge commit on `main` and push the tag:

   ```sh
   git switch main && git pull
   git tag -a v0.2.0 -m v0.2.0
   git push origin v0.2.0
   ```

The registry name is `io.github.<owner>/<name>`, and GitHub OIDC proves you own it. `tests/unit/test_publishing.py` fails if `server.json` and `pyproject.toml` disagree, or if the README lacks the `mcp-name` comment.

## Set up PyPI once

1. On PyPI, open **Your projects**, then **Publishing**, and add a pending trusted publisher: this repo, workflow `release.yml`, environment `pypi`.
2. In this repo's settings, create the `pypi` environment, and set the `PYPI_PUBLISH` variable to `true`.

No API token is needed. PyPI checks the workflow's OIDC identity, and the package gets attestations.
