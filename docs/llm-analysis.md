# Phase 5 LLM 分析设计

## 当前边界

Phase 5 已实现可控 LLM 分析基线：

```text
CleanItem
  ↓
关联评论证据
  ↓
版本化 Prompt
  ↓
OpenAI-compatible Responses API
  ↓
严格 JSON Schema 结构化输出
  ↓
Pydantic Schema 校验
  ↓
LLMAnalysisResult
  ↓
调用审计与结果入库
```

当前已实现：

- 分类。
- 地域实体提取。
- 评论情感聚合。
- 风险分数与建议。
- Prompt 版本指纹。
- 模型调用重试。
- Token 用量审计。
- 调用失败审计。
- 结果入库。
- 评论按 CleanItem 聚合。
- 无评论时跳过情感模型调用。
- 默认只预览，不调用模型。
- 每个任务使用独立严格 JSON Schema。
- 模型未完成、拒答或缺少输出文本时显式失败。

尚未实现：

- 批量异步并发调用。
- LLM 结果缓存。
- Prompt A/B 测试。
- 模型输出质量评测集。
- 与 Phase 6 评分流水线整合。

## 安全默认值

CLI 有两种模式。

### 1. 预览模式，不调用模型

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  preview-llm-analysis
```

默认选取第一条尚无 LLM 结果的 CleanItem。

指定条目：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  preview-llm-analysis \
  --clean-item-id <clean-item-id>
```

### 2. 执行模式，显式调用模型

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-llm-analysis \
  --clean-item-id <clean-item-id> \
  --execute
```

不带 `--execute` 时同样只预览：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-llm-analysis \
  --clean-item-id <clean-item-id>
```

批量处理尚无结果的条目：

```bash
uv run opinion-monitor \
  --config config/config.local.yaml \
  --env-file .env \
  run-llm-analysis \
  --all \
  --limit 10 \
  --execute
```

## 环境变量

配置引用：

```yaml
llm:
  base_url_env: OPENAI_BASE_URL
  api_key_env: OPENAI_API_KEY
  model_env: OPENAI_MODEL
```

示例：

```text
OPENAI_BASE_URL=https://api.example.com/v1
OPENAI_API_KEY=...
OPENAI_MODEL=...
```

API Key 只从环境变量读取，不写入 YAML，不进入日志。

## 模型调用

当前使用 OpenAI-compatible Responses API：

```text
POST {OPENAI_BASE_URL}/responses
```

特性：

- `Authorization: Bearer <API_KEY>`。
- 可配置 temperature。
- 可配置 `max_output_tokens`。
- 可配置超时。
- 408 / 425 / 429 / 5xx / 传输错误重试。
- 重试次数由 `llm.max_retries` 控制。
- `llm.enable_structured_output: true` 时使用 Structured Outputs：

```json
{
  "text": {
    "format": {
      "type": "json_schema",
      "name": "classification",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {
          "category": { "type": "string" },
          "confidence": { "type": "number" },
          "reason": { "type": "string" }
        },
        "required": ["category", "confidence", "reason"],
        "additionalProperties": false
      }
    }
  }
}
```

严格 Schema 会在请求前递归检查：

- 根节点是 `object`。
- 所有对象设置 `additionalProperties: false`。
- 所有对象字段同时进入 `required`。
- 可空字段使用 `["string", "null"]`。
- 数组元素具有明确的 `items` 类型。

客户端会从 `output[].content[].output_text` 提取文本，并兼容 SDK 风格的顶层 `output_text`。以下情况会被视为显式失败：

- `status` 不是 `completed`。
- `status=incomplete` 时读取 `incomplete_details.reason`。
- 输出中出现 `refusal`。
- 响应缺少输出文本。
- 输出不是有效 JSON。

Token 用量优先读取 Responses API 的 `input_tokens` / `output_tokens` / `total_tokens`，并兼容 Chat Completions 的旧字段名。

当 `llm.enable_structured_output: false` 时，客户端退回 `json_object` 格式，仅作为兼容开关；该模式不具备 JSON Schema 级稳定性。

## Structured Outputs Schema

Schema 生成逻辑位于：

```text
src/opinion_monitor/llm/schemas.py
```

四类任务均有独立 Schema：

```text
classification
geo_extraction
sentiment_analysis
risk_assessment
```

情感分析会根据 `sentiment.categories` 动态生成：

- `distribution` 的全部键。
- `dominant_sentiment` 的枚举。

因此修改情感类别配置后，无需手工维护另一份 Schema。`preview-llm-analysis` 输出的 `response_schema` 可直接审查实际发送给模型的约束。

## Prompt 管理

Prompt 文件位于：

```text
config/prompts/
```

当前包含：

```text
classification.md
geo_extraction.md
sentiment_analysis.md
risk_assessment.md
```

每个 Prompt 版本使用文件内容 SHA-256 前 12 位：

```text
4e6b46fe6969
```

Prompt 文件修改后版本自动变化，并会写入结果与审计记录。

## 分析任务

### 1. 预警资讯属性分类

输出：

```text
category
confidence
reason
```

分类枚举：

```text
sudden_event
mass_event
police_stability
livelihood_sensitive
cyber_fraud
other
```

### 2. 地域实体提取

输出：

```text
geo_evidence[]
province
city
district
location_text
confidence
```

规则：

- 只提取明确出现的地域。
- 没有地域则返回空数组。
- 不猜测行政区划。

### 3. 评论情感分析

仅在存在评论时调用模型。

输出：

```text
distribution
dominant_sentiment
negative_ratio
anger_ratio
anxiety_ratio
distrust_ratio
sentiment_score
summary
uncertainty
```

输入评论最多取：

```yaml
llm:
  max_input_comments: 100
```

评论作者身份不进入 Prompt，只传入：

- 评论内容。
- 点赞数。
- 发布时间。

没有评论时：

- 不调用情感模型。
- 生成 `unknown` 情感证据。
- 保留不确定性说明。

### 4. 风险建议

输出：

```text
risk_score
risk_reason
key_risk_factors[]
information_gaps[]
recommended_actions[]
uncertainty_notes[]
```

风险分数范围：

```text
0-100
```

约束：

- 分数只表示关注与核实程度。
- 不把未核实内容当事实。
- 不建议违法行为。
- 不引导绕过平台验证。
- 必须保留信息缺口。

## 结果与审计

### LLMAnalysisResult

保存：

- CleanItem ID。
- 模型名。
- 各 Prompt 版本。
- 最终分类。
- 分类置信度。
- 分类理由。
- 地域证据。
- 情感证据。
- 风险分数。
- 风险理由。
- 关键风险因素。
- 信息缺口。
- 建议动作。
- 不确定性说明。

### LLMAuditRecord

保存：

- CleanItem ID。
- 执行状态。
- 模型名。
- 开始时间。
- 结束时间。
- 耗时。
- 尝试次数。
- 错误信息。
- Prompt 请求摘要。
- Token 用量。

## 数据库表

Phase 5 新增：

```text
llm_analysis_audits
llm_analysis_results
```

结果与 CleanItem 一一对应；审计记录保留每次调用历史。

## 输出校验

所有模型输出必须通过 Pydantic 校验：

- 枚举合法。
- 概率范围 0-1。
- 风险分数范围 0-100。
- 必需字段存在。
- 结构符合模型。

校验失败时：

- 不写入结果表。
- 审计状态标记为 `failed`。
- 保留错误原因。
- CLI 返回非零退出码。

## 真实数据预览

2026-10-09 已用本地真实 SQLite 数据验证 Prompt 构建：

```text
CleanItem: d87eb408-7518-53b6-9555-fa0d87ddd097
关联评论: 72 条
```

生成的 Prompt：

| 任务 | Prompt 版本 |
|---|---|
| classification | `4e6b46fe6969` |
| geo_extraction | `27b881c82c4e` |
| risk_assessment | `d2b7d4a50d32` |
| sentiment_analysis | `717b0cc54c82` |

该预览没有调用外部模型，也没有消耗 Token。
2026-10-09 的结构化输出增强再次预览成功，确认输出包含四个任务的严格响应 Schema。
