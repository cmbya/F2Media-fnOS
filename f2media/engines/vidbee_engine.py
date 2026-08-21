from f2media.parsers.vidbee import parse

class VidBeeEngine:
    key="vidbee"
    async def parse(self,url,**kwargs):
        return await parse(url,**kwargs)
