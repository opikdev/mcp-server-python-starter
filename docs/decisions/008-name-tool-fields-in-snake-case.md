# 008. Name tool fields in snake_case

- **Status**: accepted
- **Context**: The SDK names each tool input after its Python parameter, so inputs are snake_case. Results used camelCase aliases, so `list_notes` returned `nextCursor` while a future input would be `next_cursor`. Models copy names between results and calls, and mixed casing invites mistakes.
- **Decision**: Name every tool input and output field in snake_case, as Python does. Tool results are plain Pydantic models. Only `ApiModel`, for backend responses, reads camelCase JSON.
- **Consequences**:
  - One casing across the tool surface, with no aliases. A contract test in `tests/integration/test_tools.py` fails on any camelCase name.
  - Breaking for clients that read `next_cursor`, `created_at`, or `client_id` in camelCase.
  - The TypeScript starter uses camelCase, the norm in that ecosystem. Each starter is consistent with itself.
