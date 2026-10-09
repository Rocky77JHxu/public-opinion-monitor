# Phase 8 端到端编排与定时试运行设计

## 当前状态

Phase 8 已实现：

- 统一 `PipelineService`。
- 热搜采集自动入库。
- MediaCrawler 采集结果自动入库。
- 待处理数据统一清洗。
- LLM 分析统一调度。
- 综合评分统一调度。
- 钉钉产出统一调度。
- 单阶段执行结果与错误记录。
- 单次端到端 CLI：`run-pipeline`。
- 常驻调度 CLI：`run-scheduler`。
- 按来源独立的下次执行时间。
- 调度状态与调度运行台账。
- 采集来源并发上限。
- 单来源执行超时。
- 默认不访问任何外部服务。
- 显式 `--execute` 才执行真实请求。

尚未实现：

- PostgreSQL 存储。
- 分布式锁与多进程部署。
- 死信队列与自动重放界面。
- 采集、分析、评分、产出的独立队列服务。

## 端到端流水线

```text
热搜采集
MediaCrawler 关键词采集
MediaCrawler 指定账号采集
        ↓
RawItem / CommentRecord 入库
        ↓
日期过滤、规范化、去重、规则分类
        ↓
LLM 分类、地域、情感、风险
        ↓
综合评分与预警级别
        ↓
StructuredOutputEvent
        ↓
钉钉自动化 Webhook
        ↓
投递状态与尝试台账
```

每个阶段输出：

- 阶段名。
- 状态。
- 开始时间。
- 结束时间。
- 耗时。
- 计数与证据。
- 错误原因。

阶段状态：

```text
succeeded
partial
failed
skipped
```

`partial` 表示至少一个来源或条目成功，同时至少一个来源或条目失败。

## PipelineService

实现位置：

```text
src/opinion_monitor/orchestration/pipeline.py
```

### 1. 热搜阶段

- 只采集指定或已启用平台。
- 单平台失败不影响其他平台。
- 解析结果直接保存为 `RawItem`。
- 每个平台可配置 `max_items_per_platform`，也可用 `--hotsearch-limit` 单次覆盖。
- 部分平台失败时阶段为 `partial`。
- 全部启用平台失败时阶段为 `failed`。

这补齐了此前“热搜只输出不入库”的断点。

### 2. MediaCrawler 阶段

支持：

- 关键词层级任务。
- 指定账号任务。
- 单任务超时。
- 条数 watchdog 记录。
- 内容 JSONL 加载。
- 评论 JSONL 加载。
- RawItem / CommentRecord 入库。

媒体采集阶段默认先入库，不在单任务内立即清洗，避免多个并发调度来源重复处理同一批 pending 数据。

### 3. 清洗阶段

统一调用 Phase 4 清洗：

- 发布时间过滤。
- URL 规范化。
- URL / 平台 ID 去重。
- SimHash 文本去重。
- 规则分类。

### 4. LLM 阶段

统一处理尚无 LLM 结果的 CleanItem：

- 分类。
- 地域实体。
- 风险研判。
- 评论情感，存在评论时调用。

失败条目会写入 `llm_analysis_audits`，后续重新执行时仍会作为待分析条目重试。

### 5. 评分阶段

统一处理已有 LLM 分析且尚无评分的 CleanItem：

- 六分项评分。
- 综合分数。
- 预警级别。
- 人工复核标记。
- 结构化事件生成。

### 6. 钉钉阶段

统一处理待投递结构化事件：

- 生成脱敏 Payload。
- 校验固定来源标识。
- 按级别过滤。
- 支持队列事件。
- 显式执行时真实投递。
- 预览时只输出 Payload 哈希。
- 成功事件不重复投递。

## 单次执行 CLI

### 安全预览

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  run-pipeline
```

不带 `--execute` 时：

- 不访问热搜平台。
- 不启动 MediaCrawler。
- 不调用 LLM。
- 不请求钉钉。
- 可以执行本地清洗与评分。
- 输出各阶段预览结果。

### 端到端真实执行

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --execute
```

该命令会按配置执行：

- 全部启用热搜平台。
- 全部启用关键词层级任务。
- 全部启用指定账号任务。
- 清洗。
- LLM 分析。
- 评分。
- 钉钉即时级别产出。

### 只执行热搜

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --source hotsearch \
  --execute
```

指定平台：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --source hotsearch \
  --hotsearch-platform weibo \
  --hotsearch-platform baidu \
  --execute
```

### 只执行 MediaCrawler

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --source media \
  --execute
```

指定关键词层级：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --source media \
  --keyword-level level_1 \
  --execute
```

指定账号：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --source media \
  --account-config-id provided_xhs_account \
  --execute
```

指定 MediaCrawler 平台：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --source media \
  --media-platform xhs \
  --execute
```

### 限制条数

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --media-limit 5 \
  --hotsearch-limit 1 \
  --llm-limit 5 \
  --output-limit 5 \
  --execute
```

### 跳过阶段

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  run-pipeline \
  --skip-llm \
  --skip-output
```

可用参数：

```text
--skip-processing
--skip-llm
--skip-scoring
--skip-output
```

### 队列事件

蓝色事件当前 `immediate=false`，需要显式包含：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --include-queued \
  --execute
```

### 失败即停止

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --fail-fast \
  --execute
```

默认策略会尽量继续后续阶段；例如部分热搜平台失败时，仍会处理成功平台的数据。

## 调度来源

调度器将配置拆成独立来源：

```text
hotsearch:<platform>
keyword_search:<level_name>
account:<account_config_id>
```

示例：

```text
hotsearch:weibo
hotsearch:baidu
keyword_search:level_1
account:provided_xhs_account
```

每个来源独立计算：

- 间隔时间。
- 最小浮动窗口。
- 最大浮动窗口。
- 下次执行时间。

热搜平台如提供完整 `interval_seconds`、`jitter_min_seconds`、`jitter_max_seconds` 覆盖值，则使用平台专属调度；否则使用热搜默认调度。

## 调度器

实现位置：

```text
src/opinion_monitor/orchestration/scheduler.py
```

### 单周期试运行

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  run-scheduler
```

默认：

- 只执行一个周期。
- 不访问外部服务。
- 会推进调度状态，用于验证下一次时间计算。

### 多周期试运行

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  run-scheduler \
  --max-cycles 3
```

如果没有来源到期，后续周期会返回空闲秒数，不发起采集。

### 真实单周期

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-scheduler \
  --execute
```

### 常驻运行

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-scheduler \
  --forever \
  --idle-seconds 30 \
  --execute
```

停止方式：

```text
Ctrl+C
```

当前常驻模式是单进程内调度，不依赖外部队列或分布式锁。

### 队列事件

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-scheduler \
  --include-queued \
  --execute
```

### 阶段与条数控制

调度 CLI 同样支持：

```text
--media-limit
--llm-limit
--output-limit
--skip-processing
--skip-llm
--skip-scoring
--skip-output
--fail-fast
```

## 调度执行策略

每个周期执行两层。

### 1. 采集层

只执行到期来源：

- 单个热搜平台。
- 单个关键词层级。
- 单个指定账号。

采集来源按 `scheduler.max_concurrent_tasks` 控制并发。

每个来源受以下配置约束：

```yaml
scheduler:
  task_timeout_seconds: 1800
```

### 2. 后续处理层

所有到期采集完成后，统一执行一次：

```text
清洗
LLM 分析
评分
钉钉产出
```

这样可以避免多个采集来源并发时重复清洗同一批 pending RawItem。

## SQLite 调度台账

Schema version 升级为 5，新增：

```text
scheduler_state
scheduler_runs
```

### scheduler_state

按来源保存：

- 来源 key。
- 来源类型。
- 上次执行时间。
- 下次执行时间。
- 更新时间。

### scheduler_runs

保存每个来源的一次调度执行：

- 调度运行 ID。
- 周期 ID。
- 来源 key。
- 来源类型。
- 状态。
- 开始时间。
- 结束时间。
- 错误原因。
- 完整 Pipeline 结果 JSON。

## 安全边界

### 默认不访问外部服务

以下命令是安全的本地预览：

```bash
uv run opinion-monitor --config config/config.local.yaml run-pipeline
uv run opinion-monitor --config config/config.local.yaml run-scheduler
```

不会访问：

- 热搜平台。
- 小红书 / 抖音等 MediaCrawler 平台。
- OpenAI-compatible LLM。
- 钉钉 Webhook。

### 显式执行

所有真实外部请求都要求：

```text
--execute
```

### 敏感信息

调度与流水线输出不包含：

- API Key。
- Webhook URL。
- 平台登录 Cookie。

## 推荐试运行顺序

1. 本地预览：

```bash
uv run opinion-monitor --config config/config.local.yaml run-pipeline
```

2. 调度单周期预览：

```bash
uv run opinion-monitor --config config/config.local.yaml run-scheduler
```

3. 小规模真实端到端：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-pipeline \
  --source media \
  --keyword-level level_1 \
  --media-limit 3 \
  --llm-limit 3 \
  --include-queued \
  --execute
```

4. 真实调度单周期：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-scheduler \
  --execute
```

5. 确认输出无误后常驻试运行：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-scheduler \
  --forever \
  --execute
```

## 验收标准

Phase 8 试运行通过应满足：

- `run-pipeline` 预览无外部请求。
- `run-pipeline --execute` 各阶段状态不为 `failed`。
- `run-scheduler` 预览能生成调度状态。
- `run-scheduler --execute` 能执行到期来源。
- SQLite `PRAGMA integrity_check` 为 `ok`。
- 外键错误为 0。
- LLM 失败数为 0 或已记录审计。
- 钉钉失败数为 0 或已记录台账。
- 重复执行不会重复投递已成功钉钉事件。
