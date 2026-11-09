"""The base for models that cross a boundary: tool results and backend API responses."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Uses snake_case fields in Python and camelCase names in JSON, both ways."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, serialize_by_alias=True
    )
