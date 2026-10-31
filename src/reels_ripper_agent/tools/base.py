from typing import ClassVar

from beartype import beartype
from pydantic import BaseModel


class Tool:
    name: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]

    @beartype
    async def execute(self, args: BaseModel) -> str:
        raise NotImplementedError

    @classmethod
    @beartype
    def schema(cls) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": cls.args_model.model_json_schema(),
            },
        }
