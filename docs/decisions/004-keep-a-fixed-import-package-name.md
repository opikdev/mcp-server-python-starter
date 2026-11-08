# 004. Keep a fixed import package name

- **Status**: accepted
- **Context**: `pik new` renames a project by replacing text in files, and can't rename folders. A package named after the project, such as `mcp_server_python_starter`, would keep the starter's name in every generated project.
- **Decision**: Name the import package `mcp_app` for every project, and rename only the distribution, the command, and the registry name.
- **Consequences**:
  - A generated project builds and runs with no folder renames.
  - Two servers from this starter can't be installed into the same environment, which `uvx` and Docker avoid by isolating each one.
  - To rename the package, move `src/mcp_app` and update `module-name` in `pyproject.toml` and the imports.
