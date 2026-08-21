
from __future__ import annotations
import asyncio, json, tempfile, os

async def parse(url, platform=None, cookie=None):
    """
    VidBee adapter.
    Uses the same yt-dlp backend style as VidBee downloader-core.
    Returns F2Media media format.
    """
    try:
        import yt_dlp
    except Exception as e:
        raise RuntimeError(f"yt-dlp backend unavailable: {e}")

    result = {}
    def hook(d):
        nonlocal result
        if d.get("status") == "finished":
            result = d

    opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "cookiefile": None,
    }
    if cookie:
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        with open(path,"w",encoding="utf-8") as f:
            f.write(cookie)
        opts["cookiefile"] = path

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = await asyncio.to_thread(ydl.extract_info, url, False)
        media=[]
        if info.get("url"):
            media.append({"type":"video","url":info["url"]})
        for f in info.get("formats",[])[-3:]:
            if f.get("url") and f.get("vcodec") != "none":
                media.append({"type":"video","url":f["url"]})
        if not media:
            raise RuntimeError("VidBee yt-dlp 未返回媒体")
        return {
            "ok":True,
            "parser":"vidbee",
            "title":info.get("title",""),
            "author":info.get("uploader",""),
            "media":media
        }
    except Exception as e:
        raise RuntimeError(f"VidBee backend: {e}")
