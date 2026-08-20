from __future__ import annotations

import asyncio
import importlib.util
from typing import Any

from ..core.cookie_format import cookie_header_for_engine
from .common import clean_url, normalize_external_result


class DouyinParseAdapter:
    """Thin adapter around DLWangSan/douyin_parse core parser (no Qt/Playwright)."""

    name = "douyin_parse"

    @staticmethod
    def available() -> tuple[bool, str]:
        spec = importlib.util.find_spec("douyin_video_parser")
        return (spec is not None, spec.origin if spec and spec.origin else "douyin_video_parser not found")

    async def parse(self, url: str, cookie: str | None) -> dict[str, Any]:
        ok, detail = self.available()
        if not ok:
            raise RuntimeError(detail)
        return await asyncio.to_thread(self._parse_sync, url, cookie)

    @staticmethod
    def _parse_sync(url: str, cookie: str | None) -> dict[str, Any]:
        from douyin_video_parser import DouyinVideoParser

        parser = DouyinVideoParser()
        parser.set_cookie(cookie_header_for_engine(cookie) or "")
        aweme_id = parser.get_video_id(url)
        if not aweme_id:
            raise RuntimeError("douyin_parse 无法提取作品 ID")
        data = parser.get_aweme_detail(aweme_id, original_url=url)
        if not isinstance(data, dict) or not isinstance(data.get("aweme_detail"), dict):
            raise RuntimeError("douyin_parse 未取得 aweme_detail；请检查抖音 Cookie")
        detail = data["aweme_detail"]
        title = str(detail.get("desc") or "")
        author = detail.get("author") or {}
        content_type = parser.get_content_type(data)

        if content_type == "video":
            qualities = parser.extract_video_qualities(data) or []
            video_url = None
            if qualities and isinstance(qualities[0], dict):
                video_url = clean_url(qualities[0].get("url"))
            video_url = video_url or clean_url(parser.extract_nwm_url(data))
            if not video_url:
                raise RuntimeError("douyin_parse 未返回视频资源")
            payload = {"type": "video", "title": title, "author": author, "url": video_url}
            return normalize_external_result(payload, "douyin", url, "douyin_parse")

        images = detail.get("images") or []
        static_urls: list[str] = []
        live_pairs: list[dict[str, str]] = []
        if isinstance(images, list):
            for image in images:
                if not isinstance(image, dict):
                    continue
                static = DouyinParseAdapter._static_image(image)
                motion = DouyinParseAdapter._live_video(image)
                if static:
                    static_urls.append(static)
                if static and motion:
                    live_pairs.append({"image": static, "video": motion})
        if not static_urls and not live_pairs:
            raise RuntimeError("douyin_parse 图集没有返回静态图片资源")
        payload = {
            "type": "live" if live_pairs else "image",
            "title": title,
            "author": author,
            "images": static_urls,
            "live_photo": live_pairs,
        }
        return normalize_external_result(payload, "douyin", url, "douyin_parse")

    @staticmethod
    def _first(value: Any) -> str | None:
        if isinstance(value, list):
            for item in value:
                out = clean_url(item)
                if out:
                    return out
        return clean_url(value)

    @staticmethod
    def _static_image(image: dict[str, Any]) -> str | None:
        for key in ("url_list", "origin_url_list", "download_url_list"):
            out = DouyinParseAdapter._first(image.get(key))
            if out:
                return out
        for key in ("origin_url", "url"):
            out = clean_url(image.get(key))
            if out:
                return out
        return None

    @staticmethod
    def _live_video(image: dict[str, Any]) -> str | None:
        video = image.get("video") or {}
        if not isinstance(video, dict):
            return None
        for key in ("play_addr", "download_addr"):
            address = video.get(key) or {}
            if isinstance(address, dict):
                out = DouyinParseAdapter._first(address.get("url_list"))
                if out:
                    return out.split("&watermark=")[0].split("&logo_name=")[0]
        for key in ("animated_url_list", "gif_url_list", "live_url_list", "motion_url_list"):
            out = DouyinParseAdapter._first(image.get(key))
            if out:
                return out
        return None
