from typing import ClassVar

from beartype import beartype
from pydantic import BaseModel, Field


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


class GetWeatherArgs(BaseModel):
    city: str = Field(description="City name, e.g. 'Tokyo'")


class GetWeather(Tool):
    name = "get_weather"
    description = "Get the current weather for a city."
    args_model = GetWeatherArgs

    @beartype
    async def execute(self, args: GetWeatherArgs) -> str:
        return f"It is 22°C and sunny in {args.city}."
