# Third-party components

F2Media bundles or integrates the following third-party projects.  Their own
licenses continue to apply to those components.

- **yt-dlp** — https://github.com/yt-dlp/yt-dlp — Unlicense.
- **gallery-dl** — https://github.com/mikf/gallery-dl (development moved to Codeberg) — GPL-2.0.
- **FFmpeg / FFprobe** — https://ffmpeg.org/ — built according to the upstream build used by F2Media; see the bundled binary's `-version` output and upstream license information.
- **Deno** — https://github.com/denoland/deno — MIT.
- **DLWangSan/douyin_parse v2.0.3** — https://github.com/DLWangSan/douyin_parse — selected parser code is bundled for Douyin parsing; see the upstream repository for its license and notices.
- **jiuhunwl/short_videos** — https://github.com/jiuhunwl/short_videos — parsing behavior is referenced/ported into F2Media's local Python adapters; upstream is MIT licensed.
- **tamnd/x-cli v0.5.0** — https://github.com/tamnd/x-cli — GNU AGPL-3.0. F2Media invokes it as a separate executable for X/Twitter parsing. The package includes the upstream LICENSE/NOTICE when available. Corresponding source is the tagged upstream release `v0.5.0`.
- **tamnd/facebook-cli v0.3.0** — https://github.com/tamnd/facebook-cli — Apache-2.0. F2Media invokes it as a separate executable for Facebook parsing. The package includes the upstream LICENSE/NOTICE when available. Corresponding source is the tagged upstream release `v0.3.0`.

The configurable free parsing APIs are remote services and are not bundled
code. Their own terms and availability apply.
