from typing import Any

class BaseEngine:
    key = "base"

    async def parse(self, url: str, **kwargs) -> dict[str, Any]:
        raise NotImplementedError
