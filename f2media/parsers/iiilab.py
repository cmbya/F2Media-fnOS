
from __future__ import annotations
import requests, re

HOSTS={
 "youtube":"https://youtube.iiilab.com",
 "twitter":"https://twitter.iiilab.com",
 "x":"https://twitter.iiilab.com",
 "instagram":"https://instagram.iiilab.com",
 "facebook":"https://facebook.iiilab.com",
}

async def parse(url, platform=None, cookie=None):
    host=HOSTS.get(platform) or HOSTS.get("facebook")
    try:
        s=requests.Session()
        r=s.get(host,timeout=15)
        r.raise_for_status()
        text=r.text
        # Generic fallback extraction for iiilab style pages
        urls=re.findall(r'https?://[^"\']+\.(?:mp4|m3u8|jpg|jpeg|png)[^"\']*',text)
        if urls:
            return {"ok":True,"parser":"iiilab","media":[{"type":"video" if "mp4" in u else "image","url":u} for u in urls]}
        raise RuntimeError("iiilab 未提取到媒体")
    except Exception as e:
        raise RuntimeError(f"iiilab: {e}")
