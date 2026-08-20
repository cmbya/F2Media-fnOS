# F2Media-fnOS

面向飞牛 fnOS x86/amd64 的多平台媒体解析与下载应用。F2 为主要下载核心，并按平台组合专用 Adapter；WebUI 支持“先解析、确认、再下载到 NAS”，同时提供带独立 API Key 的 MCP / iPhone 快捷指令入口。

## 支持目标

抖音、快手、Instagram、X/Twitter、TikTok、小红书、YouTube、哔哩哔哩、Facebook；支持电脑链接和手机分享文本。目标内容包括视频、图片、图集；动态图片/Live Photo 在底层提供动态资源时同时保存静态与动态文件。

## v0.1.9

- 修复 XHS-Downloader 2.7 `fastmcp-slim / fastmcp`：XHS sidecar 不再安装 XHS 自带 MCP 依赖，FastMCP 改为仅在上游 `run_mcp_server()` 内延迟导入；F2Media 自己负责 MCP。
- WebUI 新增独立「解析」页：解析成功后展示平台、解析器、标题、作者、媒体类型、图片/视频数量、Live Photo 配对和媒体地址；解析阶段不写下载目录。
- 解析成功后可点「下载到 NAS」；直接下载页仍保留。所有下载都由 NAS 后台执行并保存到 NAS，不把媒体返回手机。
- 固定 GitHub tag `v0.0.3` / commit `2d94221` 的 `parse-video-py` 源码接入结构化解析，优先覆盖抖音、快手、小红书、Bilibili、X；其他平台继续使用 gallery-dl / yt-dlp 探测 fallback。
- 兼容 `parse-video-py` 当前 `images[index].live_photo_url` / `image_live_photos` Live Photo 字段。
- WebUI 首次打开要求创建用户名和密码，之后使用 Basic Auth。
- MCP / iPhone 快捷指令使用另一把独立 API Key，可在设置页复制或重新生成；修改 WebUI 密码不会影响 API Key。
- Streamable HTTP MCP 地址 `/mcp`，只暴露 `parse_media`、`download_to_nas`、`get_task_status` 三个 NAS 工具。
- iPhone 快捷指令可直接调用 `/api/v1/download` 把分享文本推送给 NAS；NAS 自己解析、下载、合并并存储。另有 `/api/v1/parse` 用于只解析。
- 保留 0.1.6 的自定义 NAS 下载目录、任务日志独立弹窗、Cookie 管理、YouTube fallback、X HOME/cache 修复、KS/XHS 专用 sidecar 和 Bilibili 已验证链路。

## 安全与认证

- WebUI：用户名 + 密码，密码仅保存 PBKDF2-SHA256 哈希。
- Cookie：加密保存在 NAS 本地，日志自动脱敏。
- MCP / 快捷指令：随机独立 API Key，支持 `X-API-Key` 或 Bearer；可随时重新生成使旧 Key 失效。

## 构建

见 [BUILD_GUIDE.md](BUILD_GUIDE.md)。仓库通过 GitHub Actions 使用飞牛官方 `fnpack 1.2.3` 生成 `.fpk`。

快捷指令/MCP 请求格式见 [MCP_SHORTCUTS.md](MCP_SHORTCUTS.md)。

## 许可

F2Media 包装层：GPL-3.0-or-later。第三方组件及许可证见 `THIRD_PARTY.md`。
