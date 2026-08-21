
from __future__ import annotations
import requests,re

async def parse(url,cookie=None):
    try:
        s=requests.Session()
        r=s.post("https://fdownloader.net/zh-cn",
                 data={"url":url},
                 timeout=20,
                 headers={"User-Agent":"Mozilla/5.0"})
        text=r.text
        media=re.findall(r'https?://[^"\']+\.(?:mp4|m3u8)[^"\']*',text)
        if media:
            return {"ok":True,"parser":"fdownloader","media":[{"type":"video","url":x} for x in media]}
        raise RuntimeError("fdownloader 未返回媒体")
    except Exception as e:
        raise RuntimeError(f"fdownloader: {e}")
