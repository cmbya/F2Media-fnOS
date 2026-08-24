# Third-party components

F2Media bundles or integrates the following third-party projects.  Their own
licenses continue to apply to those components.

- **yt-dlp** — https://github.com/yt-dlp/yt-dlp — Unlicense.
- **gallery-dl** — https://github.com/mikf/gallery-dl (development moved to Codeberg) — GPL-2.0.
- **FFmpeg / FFprobe** — https://ffmpeg.org/ — built according to the upstream build used by F2Media; see the bundled binary's `-version` output and upstream license information.
- **Deno** — https://github.com/denoland/deno — MIT.
- **DLWangSan/douyin_parse v2.0.3** — https://github.com/DLWangSan/douyin_parse — selected parser code is bundled for Douyin parsing; see the upstream repository for its license and notices.
- **tamnd/x-cli v0.5.0** — https://github.com/tamnd/x-cli — GNU AGPL-3.0. F2Media invokes it as a separate executable for X/Twitter parsing. The package includes the upstream LICENSE/NOTICE when available. Corresponding source is the tagged upstream release `v0.5.0`.
- **jiuhunwl/short_videos** — https://github.com/jiuhunwl/short_videos — MIT License. F2Media bundles the four local parser classes used for Douyin, Kuaishou, Xiaohongshu and Bilibili, plus a JSON stdin/stdout adapter and a bundled PHP CLI+cURL runtime. Source pin: `87a7901018f9708663568d762e59a442a40c77c5`. The package includes the upstream LICENSE and README.

The configurable free parsing APIs are remote services and are not bundled
code. Their own terms and availability apply.
