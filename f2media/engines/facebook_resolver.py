class FacebookResolver:
    key="facebook-resolver"
    async def resolve(self,url,**kwargs):
        return {"ok":False,"url":url,"error":"facebook resolver adapter pending"}
