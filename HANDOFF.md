# 交接记录（HANDOFF）

## 当前目标

建立舆情监测系统的私有版本控制仓库与中文设计基线，然后按阶段实现采集、清洗、研判、评分与钉钉产出能力。Phase 1 已完成配置模型、环境变量展开、日志与 CLI 基线；下一阶段进入热搜采集适配器，仍不启动生产爬取。

## 更新时间

2026-10-08，Asia/Shanghai

## 仓库状态

- 工作目录：`/Users/rocky/WorkSpace/GA/test-crawler`
- 远端仓库：`git@github.com:Rocky77JHxu/public-opinion-monitor.git`
- 本地与远端主分支均为 `main`。
- 原英文基线提交已从 `main` 历史中回撤。
- 当前基线为无旧历史的中文提交。
- Phase 1 完成后待提交并推送。

## 已完成工作

### 先验调研

- 确认 MediaCrawler 支持以下平台：
  - 小红书：`xhs`
  - 抖音：`dy`
  - 快手：`ks`
  - bilibili：`bili`
  - 微博：`wb`
  - 贴吧：`tieba`
  - 知乎：`zhihu`
- 确认 MediaCrawler 支持关键词搜索、详情采集、创作者采集、评论抓取、登录态复用、代理配置、CDP 模式与 JSONL 输出。
- 梳理关键配置项：
  - `PLATFORM`
  - `KEYWORDS`
  - `CRAWLER_TYPE`
  - `ENABLE_GET_COMMENTS`
  - `CRAWLER_MAX_NOTES_COUNT`
  - `CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES`
  - `SAVE_DATA_OPTION`
  - `ENABLE_CDP_MODE`
  - `ENABLE_CDP_CONNECT_EXISTING`
  - `CDP_DEBUG_PORT`
- 确认热搜源与解析策略：
  - 微博：HTML
  - 百度：HTML
  - 知乎：HTML / 前端数据
  - 抖音：JSON
  - bilibili：JSON
- 确认需求中提供的钉钉地址属于自动化 Webhook，不等同于传统钉钉群机器人 API；真实 Payload 契约仍需单独测试。

### 设计

- 建立五层架构：采集层、原始数据层、处理层、结构化层、产出层。
- 设计目标目录结构。
- 设计核心模型：
  - `RawItem`
  - `CleanItem`
  - `AlertCategory`
  - `GeoEvidence`
  - `SentimentEvidence`
  - `RiskAssessment`
  - `StructuredOutputEvent`
- 设计采集、清洗、增强、评分与输出数据流。
- 设计示例 YAML 配置结构。
- 设计初始加权评分与预警阈值。
- 明确 MediaCrawler 集成边界。
- 明确法律合规、数据最小化、访问控制与输出安全要求。

### 工程基线

- 初始化本地 Git 仓库。
- 建立远端私有仓库连接。
- 添加 Python / uv 项目配置。
- 添加基础 CLI 入口。
- 添加 CLI 与示例配置测试。
- 添加环境变量模板与忽略规则。
- 添加中文项目文档与交接文档。
- 完成中文文档重建、验证、重新提交与远端历史替换。

### Phase 1 实现

- 新增 `opinion_monitor.config.schema`：
  - 覆盖示例 YAML 的全部主要配置节。
  - 使用 Pydantic v2 禁止未知字段。
  - 校验时区、调度窗口、权重范围、评分权重总和、预警阈值顺序、情感类别与权重一致性、平台重复、关键词重复、输出级别完整性。
- 新增 `opinion_monitor.config.loader`：
  - YAML 读取与重复键检测。
  - 递归展开 `${VAR}` 与 `${VAR:-default}`。
  - 收集与检查 `*_env` 显式环境变量引用。
  - 支持 `.env` 文件读取。
  - 进程内已有环境变量优先于 `.env` 文件。
  - 支持配置输出递归脱敏。
- 新增 `opinion_monitor.observability.logging`：
  - structlog console / JSON 两种格式。
  - 支持日志级别过滤与 ISO UTC 时间戳。
- 扩展 CLI：
  - `validate-config`
  - `inspect-env`
  - `show-config`
  - `--config`
  - `--env-file`
  - `--log-level`
  - `--log-format`
- 新增配置与 CLI 使用文档 `docs/configuration.md`。
- 新增配置加载、环境变量、CLI 与日志测试。

## 验证结果

已在本地执行：

```bash
uv sync
uv run opinion-monitor --version
uv run pytest
uv run ruff check .
uv run mypy src tests
```

结果：

- CLI 版本输出：`0.1.0`
- 测试：`15 passed`
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 11 source files`

以上结果为 Phase 1 中文基线后的完整验证结果。

## 当前阻塞点

1. 尚未进行真实热搜接口连通性测试。
2. 尚未测试钉钉自动化 Webhook 的真实 Payload 契约。
3. MediaCrawler 尚未按固定版本引入。
4. MediaCrawler 上游许可证与政府 / 生产场景适用性尚未完成法务审查。
5. 情感分类体系仍是候选方案，等待业务确认。

## 紧接着的后续步骤

1. 提交并推送 Phase 1。
2. 进入 Phase 2：实现热搜 HTTP Client、平台解析器、统一 RawItem 模型与脱敏 fixture。
3. 做只读热搜接口探针并保存脱敏 fixture。
4. 用无敏感测试 Payload 验证钉钉自动化 Webhook。
5. 在合规审查通过后再固定引入 MediaCrawler。

## 阶段实施计划

1. **Phase 1**：配置模型、环境变量展开、日志与 CLI。已完成。
2. **Phase 2**：热搜采集器与解析 fixture。
3. **Phase 3**：MediaCrawler 任务构建、执行、结果加载与平台映射。
4. **Phase 4**：清洗、日期过滤、URL / 内容去重与状态仓储。
5. **Phase 5**：OpenAI 兼容客户端与受控 JSON 分析。
6. **Phase 6**：评分、预警级别分类与可解释记录。
7. **Phase 7**：钉钉自动化输出、重试与投递台账。
8. **Phase 8**：端到端与定时试运行。

## 关键决策

- 使用 Python 3.11+ 与 `uv`。
- 系统边界使用 Pydantic v2 模型。
- 原始 Payload 作为不可变证据保存。
- MediaCrawler 隔离在 `third_party/MediaCrawler`，不与业务模块混写。
- MediaCrawler 交换格式使用 JSONL。
- 示例配置进入 Git，私密值保存在 `.env` 或被忽略的本地 YAML。
- 所有评分维度先归一化到 0-100，再加权汇总。
- 规则分类与 LLM 分类冲突时，以 LLM 分类为最终分类，但两者及置信度均保留。
- 每个分项分数、输入版本与解释必须可审计。
- 法律与合规审批通过前，不得生产部署。
