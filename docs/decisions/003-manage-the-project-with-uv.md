# 003. Manage the project with uv

- **Status**: accepted
- **Context**: A Python starter needs one way to install Python, lock dependencies, run commands, build, and publish. Combining pip, venv, pip-tools, and build gives every contributor a different setup.
- **Decision**: Use uv for Python installs, `uv.lock`, `uv run`, and the `uv_build` backend, and run the published package with `uvx`.
- **Consequences**:
  - `make sync` installs the right Python and exact dependencies in one step, in CI, Docker, and locally.
  - The Docker image installs from the same lockfile, without dev dependencies.
  - Contributors need uv, though the package itself installs with pip like any wheel.
