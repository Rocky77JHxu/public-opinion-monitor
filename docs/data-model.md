# 数据模型设计

## 建模原则

- 外部平台字段先进入 `RawItem`，不在采集器内做深度业务判断。
- 分析层只消费 `CleanItem` 与受控证据模型。
- 所有枚举使用稳定英文机器值，展示标签可在配置中中文化。
- 内部 ID 由系统生成，外部 ID 保留字符串。
- 时间统一保存为带时区信息的 UTC 时间，展示层再转换为本地时区。

## RawItem 原始条目

`RawItem` 是采集后的第一个稳定内部边界。

核心字段：

- `id`：系统内部记录 ID。
- `source_type`：来源类型，取值为 `hotsearch`、`keyword_search` 或 `account`。
- `platform`：规范化平台标识。
- `external_id`：平台侧 ID，可能不存在。
- `title`：标题。
- `content`：正文或描述。
- `url`：来源链接。
- `author_id`：作者 ID。
- `author_name`：作者名称。
- `published_at`：平台发布时间。
- `collected_at`：系统采集时间。
- `rank`：热搜排名。
- `like_count`、`forward_count`、`comment_count`、`read_count`：互动指标。
- `keyword`：命中的关键词。
- `keyword_level`：关键词层级。
- `account_config_id`：账号配置 ID。
- `raw_payload`：不可变原始数据。
- `collector_version`：采集器版本。

## CleanItem 清洗条目

`CleanItem` 表示可进入分析层的数据：

- 规范化标题与正文。
- 规范化 URL。
- 统一时间。
- 来源权重。
- 互动指标。
- 内容指纹。
- 初步属性分类、置信度与理由。
- 关联的一个或多个原始记录 ID。

## EngagementMetrics 互动指标

互动指标用于热度评分，至少包含：

- 点赞数。
- 转发数。
- 评论数。
- 阅读 / 播放数。
- 收藏数。
- 平台原始热度值。

缺失字段使用空值，不得默认为 0，避免把“未知”误判为“无热度”。

## AlertCategory 预警资讯属性分类

预警资讯属性分类：

- `sudden_event`：突发事件类，包含事故灾难、自然灾害、公共卫生事件、社会安全事件。
- `mass_event`：群众性事件类。
- `police_stability`：涉警涉稳类。
- `livelihood_sensitive`：民生敏感类。
- `cyber_fraud`：网络与诈骗专项。
- `other`：其他。

## GeoEvidence 地域实体证据

地域实体证据：

- 省。
- 市。
- 区县。
- 原始地域文本。
- 置信度。
- 提取模型或规则版本。

地域为空时必须显式保存为空列表，不应伪造默认地域。

## SentimentEvidence 情感证据

评论情感证据：

- 评论总数。
- 实际采样数。
- 各类别分布。
- 主导情感。
- 负面比例。
- 愤怒比例。
- 焦虑比例。
- 不信任比例。
- 情感得分。
- 简短证据摘要。

## CommentEvidence 评论证据

单条评论证据应保存：

- 评论 ID。
- 评论内容。
- 点赞数。
- 发布时间。
- 作者公开标识。
- LLM 分类结果。
- 分类置信度。
- 是否作为关键证据。

输出时应避免暴露无关自然人的身份信息。

## RiskAssessment 风险研判

风险研判保存：

- 关键词分类得分。
- 来源得分。
- 热度得分。
- LLM 分类得分。
- 情感得分。
- LLM 风险得分。
- 综合加权得分。
- 预警级别。
- 风险理由。
- 建议动作。
- 不确定性说明。
- 规则 / Prompt / 模型版本。

## AlertLevel 预警级别

预警级别：

- `red`：红色，立即处置。
- `orange`：橙色，关注核实。
- `blue`：蓝色，记录归档。
- `archive`：普通归档。

## StructuredOutputEvent 结构化输出事件

最终输出模型包含：

- 稳定事件 ID 与追踪 ID。
- 标题与摘要。
- 来源与 URL。
- 预警属性与级别。
- 综合得分。
- 地域证据。
- 情感证据。
- 风险研判。
- 关键证据片段。
- 建议动作。

## 指纹策略

- URL 指纹基于规范化 URL。
- 内容指纹使用 SimHash 或同等确定性算法。
- 标题与正文分别计算相似度。
- 跨平台合并必须保留各平台原始来源。
- 相似事件合并应有阈值、时间窗口与人工复核策略。
