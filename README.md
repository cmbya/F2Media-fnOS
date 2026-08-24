# F2Media

F2Media 是一个运行在飞牛 fnOS x86 上的多平台媒体解析与下载器，提供：

- WebUI 网页管理
- REST API 接口
- MCP 接口
- 图片、视频、图集和 Live Photo 下载
- Cookie 管理与按平台、按解析引擎授权
- 后台下载任务、进度、日志和失败重试

当前支持平台：抖音、快手、哔哩哔哩、小红书、Instagram、X/Twitter、YouTube、Facebook 和 TikTok。

## 解析引擎

F2Media 使用“平台独立路由”的方式选择解析引擎。每个平台都可以单独设置解析器的启用状态、优先级和 Cookie 读取权限。

默认路由如下：

| 平台 | 默认顺序 |
| --- | --- |
| 抖音 | `douyin_parse → short_videos → free-api → gallery-dl → yt-dlp` |
| 快手 | `short_videos → free-api → gallery-dl → yt-dlp` |
| 哔哩哔哩 | `short_videos → free-api → gallery-dl → yt-dlp` |
| 小红书 | `short_videos → free-api → gallery-dl → yt-dlp` |
| Instagram、Facebook、TikTok | `free-api → gallery-dl → yt-dlp` |
| X/Twitter | `x-cli → free-api → gallery-dl → yt-dlp` |
| YouTube | `free-api → yt-dlp → gallery-dl` |

其中：

- `douyin_parse`：抖音专用解析引擎，需要抖音 Cookie。
- `short_videos`：内置的本地 PHP 解析引擎，来自 [jiuhunwl/short_videos](https://github.com/jiuhunwl/short_videos)，支持抖音、快手、小红书和哔哩哔哩，不依赖公网聚合 API。
- `free-api`：可在 WebUI 中编辑的免费 API，作为备用解析方式。
- `gallery-dl`：适合图集和图片内容。
- `yt-dlp`：通用视频解析引擎。
- `x-cli`：X/Twitter 专用解析引擎。

在“设置 → 平台解析路由”中可以拖动排序、启用或关闭解析器，也可以对当前请求临时指定一个解析器。临时指定不会修改已保存的默认路由。

哔哩哔哩多 P 视频会遍历所有分 P，解析结果中的每个分 P 都会进入下载队列，不会只下载第一 P。

## Cookie 权限

Cookie 默认禁止所有解析引擎读取。

要让某个解析引擎读取 Cookie，必须同时满足两个条件：

1. 在“Cookie”页面中，授权该平台的 Cookie 可以被对应解析引擎读取。
2. 在“设置 → 平台解析路由”中，打开该平台对应解析器的“允许读取 Cookie”。

Cookie 支持以下格式：

- 浏览器导出的 Netscape `cookies.txt`
- Cookie Header，例如 `name=value; name2=value2`

Cookie 会加密保存，页面不会回显 Cookie 内容，日志中也不会输出 Cookie 值。不同平台、不同解析引擎之间的 Cookie 授权相互独立。

## 下载目录

下载文件默认按以下结构保存：

```text
YYYY-MM-DD/平台/作品标题/文件名.ext
```

例如：

```text
2026-08-24/哔哩哔哩/作品标题/作品标题 P1 第一集.mp4
2026-08-24/哔哩哔哩/作品标题/作品标题 P2 第二集.mp4
```

图集会保存为 `标题.jpg`、`标题2.jpg` 等文件。Live Photo 会同时保存静态图片和动态视频，并使用相同的基础文件名。当天存在同名作品时，目录会自动增加 ` (2)`、` (3)` 等序号。

## WebUI

安装并启动 FPK 后，通过 fnOS 应用入口打开 F2Media。

首次打开需要设置 WebUI 用户名和密码。WebUI 主要页面包括：

- 解析：输入一个或多个平台链接。
- 最近任务：查看后台下载进度、结果、日志和重试任务。
- Cookie：保存、更新、清除 Cookie，并设置解析引擎授权。
- 设置：修改下载目录、WebUI 账号、API Key 和平台解析路由。
- 日志：查看运行日志和下载任务日志。
- 自检：检查各解析引擎、FFmpeg、Deno、PHP 运行时和目录权限。

## REST API 和 MCP

REST API 与 MCP 使用独立的 API Key，WebUI 用户名和密码不会用于接口认证。

请求头：

```http
X-API-Key: 你的 API Key
```

主要接口：

```text
POST /api/v1/parse
POST /api/v1/download
POST /api/v1/parse-and-download
GET  /api/v1/tasks/{task_id}
```

常用请求示例：

```bash
curl -X POST "http://NAS地址:18082/api/v1/parse-and-download" \
  -H "X-API-Key: 你的 API Key" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.bilibili.com/video/BVxxxxxxxxxxx"}'
```

苹果快捷指令建议调用：

```text
POST /api/v1/parse-and-download
```

请求体只需要传入视频链接。F2Media 会在 NAS 后台完成解析和下载，并返回任务编号。之后可以使用 `GET /api/v1/tasks/{task_id}` 查询状态。

MCP 地址：

```text
/mcp
```

MCP 提供的主要操作名称为：`parse_media`、`download_to_nas`、`parse_and_download` 和 `get_task_status`。

## fnOS FPK 构建

项目通过 GitHub Actions 构建 fnOS x86 FPK。工作流为手动触发：

```text
Actions → Build F2Media fnOS x86 → Run workflow
```

构建流程会完成以下工作：

1. 构建 F2Media 主程序和 `gallery-dl`。
2. 下载并构建 `x-cli`、`yt-dlp`、Deno、FFmpeg 和 FFprobe。
3. 固定校验 `short_videos` 源码版本。
4. 安装 PHP 8.1 CLI 和 cURL 扩展。
5. 将 PHP、cURL 以及 ELF 依赖库一起打包进 FPK。
6. 执行 `short_videos --health`、glibc 兼容性检查、REST/MCP 自检和 FPK 反解验证。

`short_videos` 当前固定源码版本为：

```text
87a7901018f9708663568d762e59a442a40c77c5
```

构建完成后，FPK 文件和构建日志会作为 GitHub Actions Artifact 提供下载。

## 本地开发检查

项目要求 Python 3.12 或更高版本。安装开发依赖后可以运行：

```bash
python -m pytest -q
python -m compileall -q f2media scripts
python scripts/selfcheck.py
```

构建相关脚本位于 `scripts/`，fnOS 应用配置和生命周期脚本位于 `fnos/`。

## 第三方组件和许可证

请查看 [`THIRD_PARTY.md`](THIRD_PARTY.md)。其中列出了 `yt-dlp`、`gallery-dl`、FFmpeg、Deno、`x-cli`、`douyin_parse` 和 `short_videos` 等组件及其许可证信息。
