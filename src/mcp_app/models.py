"""The base for backend API responses, which often use camelCase JSON."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Reads camelCase JSON, such as the notes API's `nextCursor`, into snake_case fields.

    Tool results don't use it: the SDK names tool inputs after Python parameters, so results
    are plain models with snake_case fields too.
    """

    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)
