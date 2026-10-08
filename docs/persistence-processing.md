# Phase 4 持久化与清洗设计

## 当前边界

Phase 4 已实现本地 SQLite 持久化与清洗基线：

```text
MediaCrawler task.json
  ↓
内容 JSONL / 评论 JSONL
  ↓
RawItem / CommentRecord
  ↓
SQLite 原始层
  ↓
日期过滤
  ↓
URL 规范化与 URL 去重
  ↓
SimHash + 文本相似度去重
  ↓
CleanItem / DiscardedItem
  ↓
SQLite 清洗层与处理决策
```

当前尚未实现：

- PostgreSQL 持久化。
- 常驻调度器。
- 跨批次事件聚类优化索引。
- LLM 分析。
- 评分与产出。

## 存储配置

当前仅支持：

```yaml
storage:
  backend: sqlite
  sqlite:
    path: data/opinion_monitor.db
```

如果 `storage.backend` 不是 `sqlite`，Phase 4 CLI 与服务会显式报错，不会静默落入 SQLite。

## SQLite 表结构

### media_crawler_tasks

保存 MediaCrawler 任务定义与工作区路径，便于追溯任务来源。

### media_crawler_runs

保存单次执行状态：

- 任务 ID。
- 开始与结束时间。
- 状态。
- 返回码。
- 错误信息。
- 是否被条数 watchdog 停止。
- watchdog 实际内容计数。
- 输出文件列表。

### raw_items

保存统一 `RawItem`：

- 原始标题与正文。
- 原始 URL。
- 作者字段。
- 发布与采集时间。
- 互动数据。
- 关键词 / 账号上下文。
- 不可变 `raw_payload`。
- 采集器版本。

### comment_records

保存评论证据：

- 任务 ID。
- 平台。
- 所属笔记外部 ID。
- 评论外部 ID。
- 父评论 ID。
- 评论内容。
- 作者已脱敏标识。
- 发布时间。
- 点赞数。
- 原始评论 Payload。

### clean_items

保存清洗后的 `CleanItem`：

- 规范化 URL。
- URL 哈希。
- 64 位 SimHash。
- 标题哈希。
- 内容哈希。
- 初步规则分类。
- 分类置信度。
- 分类理由。
- 处理运行 ID。

### clean_item_sources

保存一个清洗条目与多个原始来源的关联，支持跨来源事件聚合。

### processing_runs

保存一次清洗任务的输入数、接受数与丢弃数。

### processing_item_decisions

保存每个 RawItem 的最终处理决策：

```text
accepted
discarded
```

丢弃原因和细节会以 JSON 保存，便于审计。

## 清洗策略

### 1. 发布时间过滤

配置：

```yaml
processing:
  date_filter:
    max_age_hours: 72
    missing_published_at_policy: keep_for_manual_review
```

行为：

- 发布时间超过 `max_age_hours` 的条目丢弃，原因为 `expired`。
- 缺少发布时间时默认保留待人工复审。
- 如果策略改为 `drop`，缺失发布时间的条目丢弃，原因为 `missing_published_at`。

### 2. URL 规范化

URL 会做以下处理：

- scheme 与 host 小写。
- 移除默认端口。
- 移除 `.` / `..` 路径段。
- 移除 fragment。
- 查询参数排序。
- 移除配置指定的追踪参数。
- 始终移除小红书一次性参数：
  - `xsec_token`
  - `xsec_source`

规范化后计算 SHA-256 作为 `url_hash`。

### 3. URL 与平台 ID 去重

以下任一条件命中即视为重复：

- 规范化 URL 哈希相同。
- 平台与平台外部 ID 相同。

重复条目不会删除原始数据，会记录：

```text
reason=duplicate
duplicate_of_clean_id=...
```

并把重复 RawItem ID 挂到既有 CleanItem 的来源列表。

### 4. SimHash 与文本相似度

配置：

```yaml
processing:
  deduplication:
    content:
      enabled: true
      algorithm: simhash
      title_similarity_threshold: 0.90
      content_similarity_threshold: 0.88
      cross_platform_merge: true
```

处理流程：

1. Unicode NFKC 规范化。
2. 转小写。
3. 移除多余标点和空白。
4. 计算 token 与 3-gram 特征。
5. 生成 64 位 SimHash。
6. 先用 SimHash 距离过滤明显不同的条目。
7. 再用序列相似度确认：
   - 标题相似度阈值。
   - 标题 + 正文相似度阈值。

如果 `cross_platform_merge=false`，不同平台不会进入文本相似度合并。

## 初步规则分类

清洗阶段会根据 `rules.categories` 进行初步分类：

- 突发事件类。
- 群众性事件类。
- 涉警涉稳类。
- 民生敏感类。
- 网络与诈骗专项。
- 其他。

命中多个类别时取权重最高类别。未命中归入 `other`。

该分类是 Phase 6 评分的规则输入，不会替代 LLM 分类。

## CLI

### 初始化数据库

```bash
uv run opinion-monitor --config config/config.local.yaml init-db
```

### 任务 JSON 入库并清洗

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  ingest-mediacrawler-task \
  --task-file data/media_crawler/tasks/{task_id}/task.json
```

默认输出加载统计，不输出完整原始内容。

如需完整输出：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  ingest-mediacrawler-task \
  --task-file .../task.json \
  --full
```

### 处理待清洗原始条目

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  process-pending
```

只会处理没有决策记录的 RawItem，已处理条目不会重复清洗。

## 幂等与审计

- RawItem ID 与 CommentRecord ID 稳定。
- 重复入库使用 `INSERT OR IGNORE`。
- 每次处理会生成独立 processing run。
- 每个 RawItem 只有一条最终处理决策。
- 重复入库不会增加 RawItem 数量。
- 已有处理决策的条目不会重复进入处理结果。
- 原始 Payload 不因清洗或去重而被修改。

## 2026-10-09 真实数据验证

已入库：

- 关键词任务：`火灾`
- 指定账号任务：`provided_xhs_account`

结果：

```text
RawItem: 10
CleanItem: 6
评论: 375
处理运行: 2
处理决策: 10
SQLite integrity_check: ok
foreign_key_check: 无错误
```

关键词任务中 4 条因超过 72 小时被丢弃，1 条保留。指定账号任务 5 条均保留。

重复导入同一任务时：

```text
raw_inserted=0
comments_inserted=0
pending_input=0
```

验证了入库与处理幂等性。
