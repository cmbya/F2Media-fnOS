# Third-party components

F2Media 包装层采用 GPL-3.0-or-later。构建中包含或下载以下主要第三方组件：

- F2 0.0.1.7 — Apache-2.0 — https://github.com/Johnserf-Seed/f2
- KS-Downloader 1.6 (`f8d812d`) — GPL-3.0 — https://github.com/JoeanAmier/KS-Downloader
- XHS-Downloader 2.7 (`afaf2fb`) — GPL-3.0 — https://github.com/JoeanAmier/XHS-Downloader
- FastMCP 2.14.5（XHS sidecar 固定依赖）— Apache-2.0 — https://github.com/jlowin/fastmcp
- parse-video-py 0.0.3 — MIT — https://github.com/wujunwei928/parse-video-py
- FastAPI-MCP 0.4.0 — MIT — https://github.com/tadata-org/fastapi_mcp
- gallery-dl 1.32.9 — GPL-2.0 — https://github.com/mikf/gallery-dl
- yt-dlp nightly — Unlicense — https://github.com/yt-dlp/yt-dlp
- Deno 2.9.5 — MIT — https://github.com/denoland/deno
- FFmpeg — GPL build — https://github.com/yt-dlp/FFmpeg-Builds

第三方源码/二进制均由 GitHub Actions 从对应官方项目/PyPI 获取；KS/XHS 固定 release tag 并验证提交前缀，关键运行依赖另做版本/metadata 自检。
