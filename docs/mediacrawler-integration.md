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

当前默认配置为：

```yaml
mediacrawler:
  allow_execution: false
  license_accepted: false
  pinned_ref: ""
```

因此本阶段：

- 可以生成任务。
- 可以生成命令计划。
- 可以加载 JSONL 结果。
- 不执行 MediaCrawler。
- 不启动浏览器。
- 不访问第三方目录。
- 不发起平台请求。

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

## 执行安全门槛

必须同时满足以下条件才会实际执行：

1. `mediacrawler.allow_execution: true`
2. `mediacrawler.license_accepted: true`
3. `mediacrawler.pinned_ref` 是 40 位小写 Git commit SHA
4. `third_party/MediaCrawler` 目录存在
5. 入口文件存在
6. 本地 Git `HEAD` 与 `pinned_ref` 完全一致

默认示例配置不满足以上条件，因此只生成计划。

`license_accepted` 只表示部署方已完成内部审批配置，不构成对上游许可证或平台条款的法律解释。

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

## 许可证约束

MediaCrawler 上游项目声明面向非商业学习用途。政府或生产环境使用可能超出其许可证或平台条款范围。正式引入前必须完成：

- 法律审查。
- 平台条款审查。
- 使用范围审查。
- 必要授权获取。
- 替代方案评估。

在审批完成前，本仓库不 vendoring 上游源码，也不开启执行开关。
