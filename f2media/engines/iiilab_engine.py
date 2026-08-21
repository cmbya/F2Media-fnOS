from f2media.parsers.iiilab import parse

class IIILabEngine:
    key="iiilab"
    async def parse(self,url,**kwargs):
        return await parse(url,**kwargs)
