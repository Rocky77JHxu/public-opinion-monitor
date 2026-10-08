# 热搜采集设计

## 当前边界

Phase 2 已实现热搜采集的核心链路：

```text
HotSearchHTTPClient
  ↓
HotSearchDocument
  ↓
平台 Parser
  ↓
RawItem
  ↓
HotSearchCollectionResult
```

尚未实现：

- 定时调度。
- 原始响应持久化。
- 去重与清洗。
- 热搜词扩展检索。
- 事件聚合与评分。

因此当前 CLI 的 `collect-hotsearch` 是单次采集命令，不是常驻任务。

## 支持平台

| 平台 | 配置标识 | 响应类型 | 解析策略 |
|---|---|---|---|
| 微博 | `weibo` | HTML | 表格行、标题链接、热度与标签 |
| 百度 | `baidu` | HTML | 热搜卡片、标题、链接、排名与热度 |
| 知乎 | `zhihu` | HTML 内嵌 JSON | `js-initialData` 的热榜列表 |
| 抖音 | `douyin` | JSON | `data.word_list` |
| bilibili | `bilibili` | JSON | `data.result` |

## 统一 RawItem

所有平台解析结果统一转换为 `RawItem`：

- `id`：确定性 UUID。
- `source_type`：固定为 `hotsearch`。
- `platform`：统一平台枚举。
- `external_id`：平台与排名组成的稳定标识。
- `title`：规范化标题。
- `content`：摘要或说明，可能为空。
- `url`：完整 HTTP(S) 链接，可能为空。
- `collected_at`：带时区采集时间。
- `rank`：热搜排名。
- `hot_value`：平台热度值，统一转换为整数。
- `raw_payload`：解析证据，不保存完整 HTML。
- `collector_version`：解析器版本。

## HTTP 安全与重试

`HotSearchHTTPClient` 负责：

- 从配置读取平台 URL、请求头和超时。
- 默认携带浏览器风格 `User-Agent`、`Accept` 与 `Accept-Language`。
- 跟随跳转。
- 禁用系统代理，避免开发环境代理造成不可追踪请求。
- 校验请求版本号与平台配置。
- 拒绝回环、内网、链路本地、组播、保留和未指定地址，降低 SSRF 风险。
- 对 408、425、429、5xx 与传输错误重试。
- 重试次数由 `hotsearch.defaults.max_retries` 控制。
- 重试等待由 `hotsearch.defaults.retry_backoff_seconds` 控制。

CLI 会把 `security.allow_private_network` 传入热搜采集器。该配置默认为 `false`；如需在受控内网部署中放开，必须记录审批依据并限制可配置来源。

## 平台隔离

`HotSearchCollector` 顺序执行平台任务：

- 单平台 HTTP 或解析失败不会中断其他平台。
- 每个平台输出独立 outcome。
- outcome 记录：
  - 平台。
  - 是否启用。
  - 是否成功。
  - 条目数。
  - 耗时。
  - 错误摘要。
- 所有成功平台的条目合并进入 `items`。
- 失败错误只记录异常类型与消息，不记录响应体。

## CLI

采集全部已启用平台：

```bash
uv run opinion-monitor collect-hotsearch
```

采集指定平台：

```bash
uv run opinion-monitor collect-hotsearch --platform weibo
```

采集多个平台：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  collect-hotsearch \
  --platform weibo \
  --platform baidu
```

限制每个平台输出条数：

```bash
uv run opinion-monitor collect-hotsearch --platform weibo --limit 20
```

任一平台失败即返回非零：

```bash
uv run opinion-monitor collect-hotsearch --fail-on-error
```

默认策略：

- 全部平台失败：返回非零。
- 部分平台失败：返回零，但 JSON 中会保留失败 outcome。
- `--fail-on-error`：任一启用平台失败即返回非零。

## 测试与 fixture

合成 fixture 位于：

```text
tests/fixtures/hotsearch/
```

包含：

```text
weibo.html
baidu.html
zhihu.html
douyin.json
bilibili.json
```

fixture 全部为人工构造的示例数据，不包含真实账号、真实个人数据或真实热搜内容。测试覆盖：

- 五个平台解析。
- 标题、排名、热度、URL 与内容字段。
- 相对 URL 补全。
- 平台不匹配。
- 空结果拒绝。
- 单平台失败隔离。
- 内网地址拒绝。
- CLI 条数限制。

## 2026-10-08 只读真实接口探针

| 平台 | 探针结果 | 处理结论 |
|---|---|---|
| bilibili | 成功 | 确认真实结构为 `data.trending.list`，热度字段为 `heat_score`，解析器已修正并通过回归测试 |
| 百度 | 成功 | 确认真实卡片包含置顶项、排名节点和热搜指数节点，解析器已修正排名与热度提取 |
| 抖音 | HTTP 200 但响应体为空 | 记录为平台限制或反爬风险；不绕过验证，待使用授权登录态或替代合规数据源 |
| 微博 | HTTP 200 但未解析到条目 | 页面可能要求登录态或返回验证页；不绕过验证，待配置授权会话后重试 |
| 知乎 | HTTP 403 | 平台拒绝匿名请求；不绕过验证，待配置授权会话或替代合规数据源 |

探针原则：

- 每个平台仅发起一次只读请求。
- 失败后不做绕过验证码、伪造登录态或高频重试。
- 不把真实热搜内容保存进仓库。
- 测试 fixture 继续使用人工构造数据。
