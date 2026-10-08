# 评分设计

## 评分原则

- 每个分项先归一化到 `0-100`。
- 权重总和必须等于 1。
- 每个分项得分与输入必须持久化。
- 低置信度结果进入人工复核，不自动升级预警。
- 评分用于辅助研判，不得替代必要的人工核实。

## 默认权重

| 分项 | 权重 |
|---|---:|
| 关键词属性分类 | 0.25 |
| 来源权重 | 0.10 |
| 热度 | 0.15 |
| LLM 属性分类 | 0.15 |
| 评论情感 | 0.15 |
| LLM 风险建议 | 0.20 |

计算公式：

```text
overall =
  keyword_category * 0.25
  + source * 0.10
  + heat * 0.15
  + llm_category * 0.15
  + sentiment * 0.15
  + llm_risk * 0.20
```

## 预警阈值

| 级别 | 分数 | 含义 |
|---|---:|---|
| 红色 | >= 85 | 立即处置 |
| 橙色 | >= 70 | 关注核实 |
| 蓝色 | >= 40 | 记录归档 |
| 归档 | < 40 | 不立即通知 |

阈值与权重必须保持可配置，并在每次评分结果中记录版本。

## 关键词分类得分

按配置中的预警资讯属性分类与关键词规则计算：

1. 标题、正文、账号名称与来源描述分字段匹配。
2. 命中多个类别时记录全部命中结果。
3. 取最高风险类别作为规则分类。
4. 分类得分来自类别权重与关键词强度。
5. “网传”“疑似”“待核实”等不确定性词应降低确定性，不应直接丢弃。

## 来源得分

默认来源权重示例：

| 来源类型 | 得分 |
|---|---:|
| 官方权威 | 100 |
| 主流媒体 | 90 |
| 本地媒体 | 85 |
| 认证机构账号 | 85 |
| 认证个人账号 | 70 |
| 普通社媒账号 | 60 |
| 匿名或未认证来源 | 45 |
| 未知来源 | 50 |

官方来源与网络传言同时出现时，应作为多来源证据合并，而不是简单覆盖。

## 热度得分

对有排名的热搜条目：

```text
rank_score = 100 * (1 - (rank - 1) / max_rank)
```

当平台提供实际热度值时：

```text
heat_score = 0.6 * rank_score
           + 0.4 * platform_hot_percentile_score
```

对帖子或视频，使用平台基线或滚动分位数规范化互动量，避免不同平台原始数值直接相加。

## 情感得分

情感得分基于评论采样与细粒度分类。候选类别包括：

```text
strong_negative
negative
angry
anxious
distrustful
questioning
neutral
positive
supportive
mixed
invalid
```

计算时必须记录：

- 评论总数。
- 采样数。
- 每类比例。
- 主导情感。
- 采样偏差。
- 采样时间窗口。

评论数不足时应降低情感分项置信度，而非给出高确定性结论。

## LLM 风险得分

LLM 风险建议应输出：

- 风险分数。
- 风险理由。
- 关键风险要素。
- 信息缺口。
- 建议动作。
- 置信度。

Prompt 必须要求结构化 JSON，并禁止编造不存在的来源信息。

## 规则与 LLM 冲突策略

当关键词规则分类与 LLM 分类冲突：

1. 最终分类采用 LLM 分类。
2. 保留规则分类。
3. 保留双方置信度。
4. 保留冲突说明。
5. LLM 置信度低于阈值时进入人工复核。

## 可审计性

每条研判结果必须能追溯：

- 原始条目。
- 清洗规则版本。
- 分类关键词配置版本。
- Prompt 版本。
- 模型名称。
- 各分项得分。
- 权重配置版本。
- 最终预警级别判断理由。

## Phase 6 实现

Phase 6 已实现综合评分、预警级别分类、人工复核标记、结构化事件生成与 SQLite 持久化。

### 输入

评分服务读取：

- `CleanItem`：规则分类、来源上下文、互动信息与规范化内容。
- `LLMAnalysisResult`：最终属性分类、地域证据、情感证据与风险建议。
- 清洗条目关联的全部 `RawItem`：热搜排名、平台热度值与原始互动指标。

只有存在 LLM 分析结果的 CleanItem 才会进入评分队列。

### 分项计算

#### 1. 关键词属性分类

```text
score = rules.categories[preliminary_category].weight
      * preliminary_category_confidence
```

#### 2. 来源权重

- 指定账号存在配置时，直接使用该账号的 `weight`。
- 账号配置缺失时，按 `source_weights.ordinary_social_media` 降权处理。
- 关键词检索结果按普通社媒来源处理。
- 热搜来源缺少权威性标注，使用 `source_weights.default`。

#### 3. 热度

没有热搜排名时，使用确定性的互动量对数基线：

```text
engagement_score =
  100 * log10(1 + interaction_total)
      / log10(1 + 1_000_000)
```

互动量取关联 RawItem 的 engagement 与 hot_value 中的最大值。

有热搜排名时：

```text
rank_base = 100 * (1 - (rank - 1) / 50)
rank_score = rank_base * platform_heat[platform].top_rank_weight / 100
heat_score = 0.6 * rank_score + 0.4 * engagement_score
```

当前排名基线为前 50 名。后续接入滚动分位数或平台基线后，可替换对数基线，但必须同步更新评分配置版本。

#### 4. LLM 属性分类

```text
score = rules.categories[llm_category].weight
      * llm_category_confidence
```

规则与 LLM 分类冲突时，最终分类使用 LLM 分类，并保留：

- 规则分类与置信度。
- LLM 分类与置信度。
- 冲突说明。

#### 5. 评论情感

直接使用 LLM 聚合输出的 `sentiment_score`。

Prompt 明确要求该分数为 `0-100`。为兼容早期模型误输出 `0-1` 比例的情况，评分服务会在检测到 `0 < score <= 1` 时转换为 0-100 标尺，并在分项证据中记录：

- `raw_score`
- `scale_normalized`

缺少评论情感证据时：

- 情感分项按 0 分参与加权。
- 标记需要人工复核。

#### 6. LLM 风险建议

直接使用 LLM 输出的 `risk_score`，并保留：

- 风险理由。
- 关键风险因素。
- 信息缺口。
- 建议动作。
- 不确定性说明。

### 综合分数

每个分项先归一化到 `0-100`，再乘以 `scoring.weights`：

```text
overall = Σ(component.score * component.weight)
```

分数保留 4 位小数。每个分项都会保存：

- 原始分。
- 权重。
- 加权分。
- 证据字段。
- 解释文本。

### 人工复核

以下情况会标记 `requires_manual_review=true`：

1. LLM 分类置信度低于 `scoring.manual_review_confidence`。
2. 规则分类与 LLM 分类冲突。
3. 缺少评论情感证据。

人工复核标记不会自动升级预警级别。

### 预警级别

按配置阈值从高到低判断：

```text
red >= 85
orange >= 70
blue >= 40
archive >= 0
```

判断理由写入 `alert_level_reason`。

### 评分配置版本

以下配置会生成 12 位 SHA-256 版本指纹：

- `rules`
- `source_weights`
- `platform_heat`
- `scoring`
- `alert_levels`
- `sentiment.weights`

修改任一配置都会改变评分版本，并写入研判结果。

### 结构化事件

评分完成后生成 `StructuredOutputEvent`：

- 稳定 `event_id`：由 CleanItem ID 派生的 UUIDv5。
- 稳定 `trace_id`：当前使用 CleanItem ID。
- 标题、摘要、来源与 URL。
- 最终属性分类与预警级别。
- 综合得分。
- 地域证据。
- 情感摘要。
- 关键风险因素。
- 建议动作。
- 不确定性说明。

事件不包含自然人不必要的身份信息，可直接作为 Phase 7 钉钉输出的输入。

## SQLite 持久化

Schema version 升级为 3，新增：

```text
risk_assessments
structured_output_events
```

特性：

- 按 CleanItem 幂等保存研判结果。
- 按 CleanItem 唯一保存结构化事件。
- 研判结果保留完整分项分数、证据与解释。
- 事件保留完整产出输入。
- 已初始化的 SQLite 数据库执行 `init-db` 时自动补充新表。

## CLI

### 预览评分

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  preview-risk-assessment
```

支持：

```text
--clean-item-id <id>
--all
--limit <n>
```

预览不写入数据库。

### 执行评分并入库

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  run-risk-assessment
```

默认处理第一条已有 LLM 分析且尚无评分的条目。

批量处理：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  run-risk-assessment \
  --all \
  --limit 10
```

覆盖已有评分：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  run-risk-assessment \
  --clean-item-id <id> \
  --force
```
