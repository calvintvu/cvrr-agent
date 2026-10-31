from beartype import beartype
from pydantic import BaseModel, Field

from reels_ripper_agent.tools.base import Tool


class GetWeatherArgs(BaseModel):
    city: str = Field(description="City name, e.g. 'Tokyo'")


class GetWeather(Tool):
    name = "get_weather"
    description = "Get the current weather for a city."
    args_model = GetWeatherArgs

    @beartype
    async def execute(self, args: GetWeatherArgs) -> str:
        return f"It is 22°C and sunny in {args.city}."
