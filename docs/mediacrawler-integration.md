# MediaCrawler 集成设计

## 当前状态

Phase 3 已完成主系统侧的隔离集成基线：

```text
YAML 配置
  ↓
任务构建器
  ↓
MediaCrawlerTask
  ↓
命令计划 / 隔离 Runner
  ↓
任务工作区与 JSONL 输出
  ↓
结果加载器
  ↓
RawItem
```

部署方已确认取得 MediaCrawler 使用许可。上游已通过 Git 子模块固定在：

```text
098cae5a00023ad55f00ca9665d22d0f260e2ab2
```

当前配置允许显式执行：

```yaml
mediacrawler:
  allow_execution: true
  pinned_ref: "098cae5a00023ad55f00ca9665d22d0f260e2ab2"
```

系统仍要求命令行显式传入 `--execute` 才会运行采集。普通 `plan-mediacrawler` 和不带 `--execute` 的 `run-mediacrawler` 只生成计划，不启动浏览器。

## 上游项目

上游仓库：

<https://github.com/NanmiCoder/MediaCrawler>

规划本地位置：

```text
third_party/MediaCrawler
```

不要把上游源码复制进业务模块。应将其隔离为可固定版本、可审计、可替换的第三方组件。

2026-10-08 已按上游 `cmd_arg/arg.py` 核对当前 CLI 参数。主系统生成的命令使用以下显式参数：

- `--platform`
- `--lt`
- `--type`
- `--start`
- `--keywords`
- `--creator_id`
- `--specified_id`
- `--get_comment`
- `--get_sub_comment`
- `--get_media`
- `--save_data_option`
- `--save_data_path`
- `--max_comments_count_singlenotes`
- `--crawler_max_notes_count`
- `--max_concurrency_num`

## 支持的平台标识

| 平台 | MediaCrawler 标识 |
|---|---|
| 小红书 | `xhs` |
| 抖音 | `dy` |
| 快手 | `ks` |
| bilibili | `bili` |
| 微博 | `wb` |
| 贴吧 | `tieba` |
| 知乎 | `zhihu` |

## 任务构建

### 关键词任务

来源：

```yaml
keyword_search:
  levels:
    level_1:
      enabled: true
      platforms: [xhs, dy]
      keywords: [示例关键词]
```

系统会为每个：

```text
启用的关键词层级 × 平台 × 关键词
```

生成一个独立任务。

任务包含：

- 稳定任务 ID。
- 平台。
- 采集类型 `search`。
- 关键词。
- 关键词层级。
- 最大条目数。
- 最大评论数。
- 超时时间。
- 工作区目录。
- 输入文件路径。
- 输出文件路径。

### 指定账号任务

来源：

```yaml
account_search:
  accounts:
    example:
      enabled: true
      platform: dy
      external_id: account-id
      crawl_type: creator
      max_items: 30
```

系统会为每个启用账号生成 `creator` 或 `detail` 任务。

## 执行前提

许可证人工确认字段已按你的授权结论移除。实际执行仍需要：

1. `mediacrawler.allow_execution: true`
2. `mediacrawler.pinned_ref` 是 40 位小写 Git commit SHA
3. `third_party/MediaCrawler` 子模块存在
4. 上游入口存在
5. 子模块本地 `HEAD` 与 `pinned_ref` 完全一致
6. CLI 显式传入 `--execute`

固定版本校验用于防止运行未审查代码，不属于许可证围栏。

## 隔离 Runner

Runner 使用：

```python
asyncio.create_subprocess_exec(...)
```

不使用 shell，避免命令注入。

每个任务有独立工作区：

```text
data/media_crawler/tasks/{task_id}/
```

规划包含：

```text
task.json
stdout.log
stderr.log
*.jsonl
```

Runner 会：

- 将任务定义写入 `task.json`。
- 将子进程标准输出写入 `stdout.log`。
- 将子进程标准错误写入 `stderr.log`。
- 使用配置的超时时间。
- 超时后先 terminate。
- terminate 后仍不退出则 kill。
- 校验本地 MediaCrawler commit SHA。
- 根据退出码输出成功或失败状态。

## 命令计划示例

生成计划：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  plan-mediacrawler \
  --source keyword \
  --platform xhs
```

输出包含：

- `allow_execution`
- 任务数量。
- 每个任务的完整 `MediaCrawlerTask`。
- 每个任务的 argv。
- 工作区。
- 输入 / 输出路径。
- stdout / stderr 路径。
- 超时时间。

该命令不会执行采集。

## 单任务执行

关键词任务默认只生成计划：

```bash
uv run opinion-monitor \
  run-mediacrawler \
  --source keyword \
  --platform xhs \
  --keyword 示例关键词
```

显式执行：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  run-mediacrawler \
  --source keyword \
  --platform xhs \
  --keyword 示例关键词 \
  --execute
```

指定账号任务显式执行：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  run-mediacrawler \
  --source account \
  --account-config-id example \
  --execute
```

执行完成后，集成服务会自动扫描任务工作区中的 JSONL 文件并转换为 `RawItem`。如果登录态缺失、平台要求验证或任务失败，结果中的 `run.status` 会保留失败原因，不会绕过验证。

## JSONL 结果加载

MediaCrawler 输出 JSONL 后，可加载为统一 `RawItem`：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  load-mediacrawler \
  --path data/media_crawler/tasks/{task_id}/contents.jsonl \
  --task-id {task_id} \
  --platform xhs \
  --source-type keyword_search \
  --keyword 示例关键词 \
  --keyword-level 1
```

如果不知道实际文件名，可先用 API 或脚本扫描任务目录：

```python
from opinion_monitor.collectors.mediacrawler import discover_jsonl_files

files = discover_jsonl_files("data/media_crawler/tasks/{task_id}")
```

结果加载器会：

- 逐行解析 JSON。
- 要求行根节点为对象。
- 将平台字段映射为统一字段。
- 将发布时间规范化为 UTC。
- 将互动指标转为整数。
- 保留原始记录到 `raw_payload`。
- 生成稳定 `RawItem.id`。
- 记录单行失败原因。
- 不因单行失败丢弃整个文件。

支持的字段别名包括：

| 目标字段 | 来源字段示例 |
|---|---|
| 外部 ID | `note_id`、`aweme_id`、`video_id`、`content_id`、`post_id`、`id` |
| 标题 | `title`、`display_title`、`name`、`subject` |
| 正文 | `desc`、`description`、`content`、`text`、`excerpt` |
| URL | `note_url`、`url`、`content_url`、`link`、`uri` |
| 发布时间 | `publish_time`、`published_at`、`create_time`、`created_at`、`time` |
| 作者 ID | `user_id`、`author_id` |
| 作者名 | `nickname`、`author_name`、`username` |
| 点赞 | `liked_count`、`like_count`、`digg_count` |
| 评论 | `comment_count` |
| 分享 | `share_count`、`forward_count` |
| 阅读 | `read_count`、`view_count`、`play_count` |

## 上游配置映射

主系统通过 `upstream_entry.py` 启动固定版本：

- 不修改上游源码。
- 不绕过登录、验证码或平台反滥用机制。
- 在启动前映射 CDP 开关。
- 映射 CDP 端口。
- 映射 headless 设置。
- 映射登录态保存设置。
- 映射请求休眠时间。
- 保留上游 JSONL 输出目录。

MediaCrawler 会按平台在子模块的 `browser_data` 目录中复用登录态。该目录位于子模块工作区内，不会被主仓库提交。

## 小红书初始状态兼容层

固定上游版本的小红书创作者页解析在部分页面中会遇到 JavaScript 字面量：

```text
undefined
new Set([])
new Map([])
```

主系统新增：

```text
src/opinion_monitor/collectors/mediacrawler/xhs_compat.py
```

该兼容层在 `upstream_entry.py` 启动时替换上游 `XiaoHongShuExtractor` 的解析方法：

- 非贪婪提取 `window.__INITIAL_STATE__`。
- 将 `undefined`、`NaN`、`Infinity` 转为 `null`。
- 将空 `Set` / `Map` 转为 JSON 数组 / 对象。
- 非法或风控页返回 `None`。
- 不修改子模块源码。
- 不绕过登录、验证码或平台限制。

2026-10-08 已用同一账号链接复测成功，输出 5 条内容与 8 条评论。

## 条数 watchdog

上游小红书搜索流程会把小于 20 的 `crawler_max_notes_count` 强制提升到 20。为避免超出主系统配置，当前使用双层保护。

### 1. 小红书详情请求限流

`upstream_entry.py` 会根据环境变量 `OPINION_MONITOR_MAX_ITEMS` 在详情任务外层计数：

```text
达到 max_items
  ↓
后续详情任务直接返回 None
  ↓
不再请求第 max_items+1 条详情
  ↓
继续完成已采集条目的评论阶段
```

这样可以避免在内容达到 5 条时立刻杀进程导致评论缺失。

### 2. 通用输出 watchdog

Runner 会按配置轮询任务目录：

```yaml
mediacrawler:
  watchdog_enabled: true
  watchdog_poll_seconds: 0.25
```

统计规则：

- 只统计文件名包含 `content` 且不包含 `comment` 的 JSONL。
- 只统计能解析为 JSON 对象的完整行。
- 半写行和非法 JSON 不计数。
- 如果内容记录数超过 `max_items`，立即 terminate 上游子进程。

如果 watchdog 触发，运行结果会保留：

```text
stopped_by_watchdog=true
watchdog_content_count=<实际完整记录数>
```

### 2026-10-08 真实复测

关键词：

```text
火灾
```

配置：

```text
max_items=5
max_comments=100
```

结果：

```text
内容：5 条
评论：150 条
状态：succeeded
stopped_by_watchdog=false
```

说明详情请求限流已在上游处理完 5 条前生效，无需通用 watchdog 强制终止进程。

## 任务 ID 策略

任务 ID 使用确定性 UUIDv5，命名空间输入包含：

- 来源类型。
- 平台。
- 采集类型。
- 关键词或账号 ID。
- 关键词层级或账号配置 ID。

同一配置生成的任务 ID 稳定，便于追踪与幂等。未来执行记录会使用独立运行 ID 区分多次调度。

## 运行限制

- 每个平台登录上下文默认最多同时执行一个任务。
- 使用保守的条目数与评论数。
- 浏览器登录态保存在 Git 外。
- 禁止记录 Cookie、密码或令牌。
- 不将用户输入拼接进 shell。
- 不绕过登录、验证码或平台反滥用机制。
- 连续认证或传输失败时停止任务并告警。
- 原始输出设置有限保留周期。

## 许可证记录

部署方已于 2026-10-08 确认 MediaCrawler 使用许可已取得。上游以 Git 子模块方式固定在：

```text
098cae5a00023ad55f00ca9665d22d0f260e2ab2
```

后续仍应保留许可文件、授权范围、审批记录与平台条款核查记录，并确保实际采集范围不超出授权范围。
