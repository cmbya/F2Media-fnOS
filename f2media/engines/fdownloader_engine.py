from .base import BaseEngine

class FDownloaderEngine(BaseEngine):
    key="fdownloader"
    async def parse(self,url,**kwargs):
        return {"ok":False,"parser":self.key,"error":"fdownloader adapter pending"}
