from f2media.parsers.fdownloader import parse

class FDownloaderEngine:
    key="fdownloader"
    async def parse(self,url,**kwargs):
        return await parse(url,**kwargs)
