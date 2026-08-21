from .base import BaseEngine

class IIILabEngine(BaseEngine):
    key = "iiilab"

    async def parse(self, url: str, **kwargs):
        return {
            "ok": False,
            "parser": "iiilab",
            "error": "iiilab engine adapter not enabled yet"
        }
