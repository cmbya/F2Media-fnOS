# F2Media fnOS

F2Media is an fnOS x86 native application for parsing and downloading media to a NAS from Douyin, Kuaishou, Bilibili, Xiaohongshu, Instagram, X/Twitter, YouTube, Facebook and TikTok.

## 0.2.x architecture

- WebUI parsing never writes media files. A successful parse must expose actual downloadable media resources.
- Douyin route: `douyin_parse -> short_videos local logic -> configurable free API -> gallery-dl -> yt-dlp`.
- Other platforms skip unsupported local parsers but keep the agreed order: local short_videos logic (where supported), configurable free API, gallery-dl, yt-dlp.
- `parse-video-py`, F2, KS-Downloader and XHS-Downloader are removed from runtime/build dependencies.
- REST API and Streamable HTTP MCP share one independent API key; WebUI username/password remain separate.
- MCP tools: `parse_media`, `download_to_nas`, `parse_and_download`, `get_task_status`.
- Downloads are stored as `YYYY-MM-DD/<平台>/<标题>/<标题>.<ext>`. Duplicate title directories use `标题 (2)`, `标题 (3)`, etc.
- Live Photo is treated as an image/video pair; missing either side results in a partial task.
- Video output prefers MP4/H.264/AAC compatible with iPhone and Windows, then highest quality within that compatibility preference.
- Cookie configuration is per platform and secrets are redacted from logs.
- Free parser APIs can be added/edited/tested/deleted from WebUI, including URL, method, URL parameter, headers, fixed parameters, field mappings and priority.
- `gallery-dl` and `yt-dlp` can be updated from WebUI. Updates stage and self-test the new executable, keep the previous version, and support one-click rollback.

## Build

The GitHub Actions workflow uses official `fnpack 1.2.3`, Python 3.12, `gallery-dl`, current `yt-dlp` nightly, FFmpeg/FFprobe, Deno and the `douyin_parse` v2.0.3 core parser.

Trigger **Build F2Media fnOS x86** manually and provide an `X.Y.Z` version. The workflow runs unit tests, compile checks, runtime REST/MCP authentication checks, a Debian 12 / glibc 2.36 compatibility gate and reverse verification of the generated `.fpk`.
