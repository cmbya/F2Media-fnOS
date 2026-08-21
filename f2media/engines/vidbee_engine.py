from .base import BaseEngine

class VidBeeEngine(BaseEngine):
    key = "vidbee"

    async def parse(self, url: str, **kwargs):
        # VidBee engine adapter placeholder.
        # Keeps unified interface so downloader-core can be integrated here.
        return {
            "ok": False,
            "parser": "vidbee",
            "error": "VidBee engine adapter not enabled yet"
        }
