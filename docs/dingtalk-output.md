# Phase 7 钉钉自动化产出设计

## 当前边界

Phase 7 已实现：

```text
StructuredOutputEvent
  ↓
安全脱敏
  ↓
钉钉 Payload 格式化
  ↓
dry-run / 真实 Webhook 投递
  ↓
重试与业务响应校验
  ↓
投递状态与请求尝试台账
```

当前支持：

- `automation_json`：向钉钉自动化 Webhook 推送通用 JSON 事件。
- `markdown`：输出钉钉机器人兼容的 Markdown 消息结构。
- 按预警级别启用 / 禁用。
- `immediate=true` 与队列事件区分。
- dry-run 默认安全模式。
- 显式 `--execute` 才发起真实请求。
- Webhook URL 公共地址校验。
- 手机号与身份证号脱敏。
- 用户 ID 字段遮蔽。
- HTTP 超时、重试与退避。
- HTTP 状态码与业务错误校验。
- 投递状态幂等控制。
- 每次请求 / dry-run 的尝试台账。

尚未实现：

- 常驻调度器自动触发。
- 多 Webhook 目标。
- 死信队列与人工重放界面。

## 钉钉自动化契约

钉钉自动化 Webhook 接收外部系统推送的 JSON 数据。触发流程可以在钉钉内解析字段、格式化群消息并通知责任人或群组。

官方文档要点：

- Webhook 地址等同等密钥，不得泄露。
- 自动化流程可以接收任意 JSON 对象，并在流程内引用字段。
- 若使用“源数据解析”，可以接收钉钉机器人兼容的消息结构，例如 Markdown。
- 触发流程可配置关键词；请求体中必须包含该关键词。

参考：

```text
https://open.dingtalk.com/document/connection/webhook-sync-data
```

## 配置

示例：

```yaml
output:
  dingtalk:
    enabled: true
    webhook_url_env: DINGTALK_AUTOMATION_WEBHOOK_URL
    trigger_keyword: 舆情预警
    timeout_seconds: 15
    max_retries: 3
    retry_backoff_seconds: 5
    send_mode: automation_json
    dry_run: true
    levels:
      red:
        enabled: true
        immediate: true
      orange:
        enabled: true
        immediate: true
      blue:
        enabled: true
        immediate: false
      archive:
        enabled: false
        immediate: false
```

### 字段说明

- `enabled`：钉钉产出全局开关。
- `webhook_url_env`：只保存环境变量名，不保存真实 URL。
- `trigger_keyword`：必须与钉钉自动化触发关键词一致。
- `timeout_seconds`：单次 HTTP 请求超时。
- `max_retries`：失败后的额外重试次数。
- `retry_backoff_seconds`：固定退避时间。
- `send_mode`：
  - `automation_json`
  - `markdown`
- `dry_run`：配置层默认值；CLI 只有显式传入 `--execute` 才真实请求。
- `levels`：按预警级别控制产出。
- `immediate`：
  - `true`：可被自动即时产出。
  - `false`：进入人工或批处理队列；CLI 需要 `--include-queued` 才选取。

## automation_json Payload

默认模式输出：

```json
{
  "schema_version": 1,
  "source_system": "opinion_monitor",
  "event_type": "opinion_monitor.alert",
  "keyword": "舆情预警",
  "event_id": "...",
  "trace_id": "...",
  "dedup_key": "...",
  "occurred_at": "...",
  "data": {
    "event_id": "...",
    "trace_id": "...",
    "clean_item_id": "...",
    "title": "...",
    "summary": "...",
    "source_type": "...",
    "platform": "...",
    "url": "...",
    "category": "...",
    "alert_level": "...",
    "alert_level_label": "...",
    "overall_score": 0,
    "geo_evidence": [],
    "sentiment_summary": "...",
    "key_risk_factors": [],
    "recommended_actions": [],
    "uncertainty_notes": [],
    "created_at": "..."
  }
}
```

用途：

- `keyword` 满足钉钉触发关键词。
- `source_system` 是固定来源标识，当前恒为 `opinion_monitor`，用于识别数据由本系统发出。
- `event_id` 与 `dedup_key` 支持钉钉侧幂等。
- `trace_id` 贯穿采集、清洗、分析、评分与产出。
- `data` 保留完整业务事件，钉钉自动化流程可按字段引用。

## markdown Payload

`send_mode: markdown` 时输出钉钉机器人兼容结构：

```json
{
  "msgtype": "markdown",
  "markdown": {
    "title": "舆情预警｜橙色 - 关注核实｜标题",
    "text": "..."
  }
}
```

Markdown 内容包含：

- 来源系统标识。
- 预警级别。
- 标题。
- 综合得分。
- 预警属性。
- 来源平台。
- 事件 ID。
- 风险摘要。
- 情感摘要。
- 关键风险因素。
- 建议动作。
- 追踪 ID。
- 来源链接。

## 安全策略

### URL 安全

真实请求前会校验 Webhook URL：

- 只允许 HTTP / HTTPS。
- 默认拒绝内网、回环、链路本地、未指定、组播与保留地址。
- 默认禁止跟随重定向，降低 SSRF 风险。
- `security.allow_private_network: true` 仅应在内网授权流程中使用。

### 内容脱敏

构建 Payload 前会处理：

- 中国大陆手机号。
- 18 位身份证号。
- `author_id` / `user_id` 类字段。

脱敏后的 Payload 会计算 SHA-256 指纹并写入台账。

### 密钥安全

- Webhook URL 只从环境变量读取。
- 不写入 YAML。
- 不写入日志。
- CLI 输出只包含 Payload 与哈希，不包含 Webhook URL。

## 响应校验

HTTP 2xx 不直接视为成功，还会检查响应体：

- `errcode` 非零视为失败。
- `code` 非零视为失败。
- `success=false` 视为失败。
- `status=failed/error/fail` 视为失败。
- 空 Body 按 2xx 成功处理。
- `ok` / `success` 纯文本按成功处理。
- 非法 JSON 按失败处理。

可重试状态：

```text
408 / 425 / 429 / 500 / 502 / 503 / 504
```

其余 4xx 不重试。

## SQLite 台账

Schema version 升级为 4，新增：

```text
dingtalk_deliveries
dingtalk_delivery_attempts
```

### dingtalk_deliveries

每个结构化事件一条投递状态：

- 事件 ID。
- CleanItem ID。
- 预警级别。
- 发送模式。
- 状态。
- 尝试次数。
- 是否即时。
- 是否 dry-run。
- Payload 哈希。
- 完整脱敏 Payload。
- HTTP 状态码。
- 响应体。
- 错误原因。
- 创建与更新时间。

状态：

```text
running
succeeded
failed
dry_run
skipped
```

只有 `succeeded` 表示真实投递成功，后续默认不会重复投递。

### dingtalk_delivery_attempts

保存每次真实请求或 dry-run：

- 尝试序号。
- 状态。
- 是否 dry-run。
- Payload 哈希。
- HTTP 状态码。
- 响应体。
- 错误原因。
- 开始与结束时间。

重试从既有 `attempt_count` 后继续编号，便于审计。

## CLI

### 预览 Payload

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  preview-dingtalk-output
```

默认只选取已启用且 `immediate=true` 的待投递事件。

包含非即时队列：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  preview-dingtalk-output \
  --include-queued
```

指定事件：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  preview-dingtalk-output \
  --event-id <event-id>
```

预览不发送请求，也不写台账。

### dry-run 投递

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  send-dingtalk-output \
  --include-queued
```

dry-run：

- 不访问 Webhook。
- 校验并生成 Payload。
- 写入一条 `dry_run` 状态。
- 写入一条 dry-run 尝试记录。

### 真实投递

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  send-dingtalk-output \
  --include-queued \
  --execute
```

显式 `--execute` 后才会发起真实 HTTP 请求。

指定事件重发：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  send-dingtalk-output \
  --event-id <event-id> \
  --force \
  --execute
```

## 2026-10-09 真实数据验证

已在本地真实 SQLite 数据上完成：

- Schema version 3 到 4 迁移。
- 真实结构化事件 Payload 预览。
- 事件：
  - `929819bf-7fbc-59a2-aba8-1756e79a05e5`
  - 预警级别：`blue`
  - 模式：`automation_json`
- Payload SHA-256：
  - `ad0fdba440ea00a373c8252801a8edf64293b06b90842b3db55ac1ba2a12c83d`
- dry-run 成功。
- Payload 已包含固定来源标识：
  - `source_system=opinion_monitor`
- 台账：
  - `dingtalk_deliveries=1`
  - `dingtalk_delivery_attempts=2`

## 当前阻塞点

真实 Webhook 契约冒烟未能发出请求：当前 `.env` 中：

```text
DINGTALK_AUTOMATION_WEBHOOK_URL=replace-me
```

该值仍是占位符。客户端已按预期拒绝请求并记录失败原因，没有向外部服务发送数据。

需要将该项替换为钉钉自动化流程提供的真实 Webhook URL 后，再执行：

```bash
env -u DINGTALK_AUTOMATION_WEBHOOK_URL \
  uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  send-dingtalk-output \
  --event-id <event-id> \
  --force \
  --execute
```
