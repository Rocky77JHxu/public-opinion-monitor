# 舆情监测系统

本项目是一个面向受控合规场景的舆情采集、标准化、研判、评分与通知流水线。当前项目处于 **Phase 7：钉钉自动化产出** 阶段。MediaCrawler 已固定接入，SQLite 原始层 / 评论证据 / 清洗层 / LLM 分析层 / 评分层已实现，Responses API 严格结构化输出、综合评分、预警级别、结构化事件、钉钉 Payload 构建、dry-run、重试与投递台账基线已可用；未启动常驻爬取任务。

## 系统定位

系统规划为五个层次：

1. **采集层**：定时采集热搜、按关键词检索、按指定账号检索。
2. **原始数据层**：保存不可变的原始记录、采集状态与任务结果。
3. **处理层**：清洗、规范化、去重、分类、地域实体提取、评论情感分析与评分。
4. **结构化层**：生成研判条目、证据包、分项得分、综合得分与预警级别。
5. **产出层**：通过钉钉自动化 Webhook 输出结构化事件，并记录投递状态。

详细设计见：

- [架构设计](docs/architecture.md)
- [数据流设计](docs/data-flow.md)
- [数据模型设计](docs/data-model.md)
- [评分设计](docs/scoring.md)
- [MediaCrawler 集成设计](docs/mediacrawler-integration.md)
- [配置与 CLI 使用说明](docs/configuration.md)
- [持久化与清洗设计](docs/persistence-processing.md)
- [LLM 分析设计](docs/llm-analysis.md)
- [钉钉自动化产出设计](docs/dingtalk-output.md)
- [热搜采集设计](docs/hotsearch.md)

## 当前状态

已完成：

- 私有 Git 仓库与远端 `main` 基线。
- Python / uv 项目配置。
- Pydantic 配置 Schema 与示例配置校验。
- YAML 重复键检测。
- `${VAR}` 与 `${VAR:-default}` 环境变量展开。
- `*_env` 显式环境变量引用检查。
- `.env` 文件加载与进程内环境优先策略。
- structlog console / JSON 日志。
- `validate-config`、`inspect-env`、`show-config` CLI 子命令。
- 统一 `RawItem` 领域模型。
- 微博、百度、知乎、抖音、bilibili 热搜解析器。
- 热搜 HTTP 客户端、公共地址校验、超时与重试。
- 单平台失败隔离的采集编排器。
- `collect-hotsearch` CLI 子命令。
- MediaCrawler 关键词 / 账号任务构建器。
- MediaCrawler 隔离命令计划与安全执行门槛。
- MediaCrawler JSONL 结果发现、加载与字段归一化。
- MediaCrawler 条数 watchdog 与小红书详情请求限流。
- SQLite 原始层、评论证据与清洗层持久化。
- 日期过滤、URL 规范化、URL 去重与 SimHash 文本去重。
- `init-db`、`ingest-mediacrawler-task`、`process-pending` CLI。
- OpenAI-compatible Responses API 客户端与 Structured Outputs 严格 JSON 解析。
- 预警分类、地域实体、评论情感与风险建议 Prompt。
- LLM 调用审计与结果入库。
- `preview-llm-analysis`、`run-llm-analysis` CLI。
- 六分项综合评分：规则分类、来源、热度、LLM 分类、情感与 LLM 风险。
- 预警级别分类：红色、橙色、蓝色、归档。
- 低置信度、规则 / LLM 冲突与缺少情感证据的人工复核标记。
- 评分配置版本指纹与分项证据解释。
- 风险研判与结构化输出事件持久化。
- `preview-risk-assessment`、`run-risk-assessment` CLI。
- 钉钉 `automation_json` 与 `markdown` Payload 构建。
- 固定来源标识 `source_system=opinion_monitor`。
- 手机号、身份证号与用户 ID 字段脱敏。
- Webhook 公共地址校验、超时、重试与业务响应校验。
- 钉钉投递状态与逐次尝试台账。
- `preview-dingtalk-output`、`send-dingtalk-output` CLI。
- `plan-mediacrawler` 与 `load-mediacrawler` CLI 子命令。
- 五个平台的合成 fixture 与回归测试。

尚未实现：

- 常驻调度器。
- MediaCrawler 常驻调度与 PostgreSQL 存储。
- LLM 批量并发调用、结果缓存与质量评测集。
- 真实钉钉 Webhook 契约测试与真实结构化事件端到端投递已完成。
- 常驻调度器自动触发钉钉产出。

## 开发环境

项目使用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境：

```bash
uv sync
uv run opinion-monitor --version
uv run pytest
```

常用命令：

```bash
uv run opinion-monitor validate-config
uv run opinion-monitor inspect-env
uv run opinion-monitor show-config --format json
uv run opinion-monitor collect-hotsearch --platform weibo
uv run opinion-monitor plan-mediacrawler --source keyword
uv run opinion-monitor preview-llm-analysis
uv run opinion-monitor preview-risk-assessment
uv run opinion-monitor preview-dingtalk-output --include-queued
uv run opinion-monitor init-db
uv run opinion-monitor ingest-mediacrawler-task --help
uv run opinion-monitor run-mediacrawler --help
uv run opinion-monitor load-mediacrawler --help
```

本地测试前先复制环境变量模板：

```bash
cp .env.example .env
```

配置示例位于 `config/config.example.yaml`。本地私密配置应复制为 `config/config.local.yaml`，该文件已被 Git 忽略。详细规则见 [配置与 CLI 使用说明](docs/configuration.md)。
