# F2Media

F2Media is a native fnOS x86 media parser/downloader with WebUI, REST API and
MCP access. It targets Douyin, Kuaishou, Bilibili, Xiaohongshu, Instagram,
X/Twitter, YouTube, Facebook and TikTok, including image galleries and Live
Photo pairs where the source platform exposes them.

## v0.2.2 parser routing

Parser order is no longer hard-coded. In **设置 → 平台解析路由**, every platform
shows every installed parser plus each configured free API as its own route
item. Recommended parsers start enabled; non-recommended parsers remain visible
and can be enabled manually. Items can be reordered by drag-and-drop or ↑ / ↓,
disabled individually, saved per platform, or reset to defaults.

The parse page also supports a one-time parser override. **自动** follows the
saved platform route; selecting one parser uses only that parser for the current
request and does not modify the saved route.

Specialized engines added in v0.2.2:

- X/Twitter: `x-cli` v0.5.0.
- Facebook: `facebook-cli` v0.3.0.
- Facebook `/share/...` links first pass through a Facebook-only URL resolver;
  no other platform is sent through this resolver.

`yt-dlp`, `gallery-dl`, `x-cli` and `facebook-cli` can be checked/updated from
the WebUI. An update is staged and version-checked before replacement, and the
previous version is retained for one-click rollback.

## Download layout

Downloads use the configured root directory and are stored as:

```text
YYYY-MM-DD/平台/标题/标题.ext
```

Multi-image posts use `标题.jpg`, `标题2.jpg`, ...; Live Photo items retain both
static image and motion video with matching base names. Duplicate title folders
become `标题 (2)`, `标题 (3)`, etc.

## API / MCP

WebUI authentication is username/password based. REST API and MCP use the same
separate API key. The main MCP operations are `parse_media`,
`download_to_nas`, `parse_and_download` and `get_task_status`.

The iPhone Shortcut flow should call the REST `parse-and-download` endpoint
with a pure URL; the NAS performs parsing and download in the background and
returns a task id.

See `THIRD_PARTY.md` for bundled third-party components and their licenses.
