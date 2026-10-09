# 交接记录（HANDOFF）

## 当前目标

建立舆情监测系统的私有版本控制仓库与中文设计基线，然后按阶段实现采集、清洗、研判、评分与钉钉产出能力。Phase 8 已完成统一端到端 PipelineService、热搜自动入库、MediaCrawler 统一入库、清洗 / LLM / 评分 / 钉钉统一调度、按来源独立调度状态、并发上限、超时、单次 run-pipeline 与常驻 run-scheduler CLI；本地安全预览与调度试运行已通过，尚未执行 Phase 8 全量真实外部请求。

## 更新时间

2026-10-09，Asia/Shanghai

## 仓库状态

- 工作目录：`/Users/rocky/WorkSpace/GA/test-crawler`
- 远端仓库：`git@github.com:Rocky77JHxu/public-opinion-monitor.git`
- 本地与远端主分支均为 `main`。
- 原英文基线提交已从 `main` 历史中回撤。
- 当前基线为无旧历史的中文提交。
- Phase 1 已提交推送，提交为 `76da3d9`。
- Phase 2 已验证、提交并推送，提交为 `00306f1`，后续解析修复提交为 `9eb051e`。
- Phase 3 主系统侧基线已提交为 `efb8828`。
- MediaCrawler 固定版本接入与条数保护已提交推送，最新已推送提交为 `8b8fa52`。
- Phase 4 已验证、提交并推送，提交为 `38577ee`。
- Phase 5 已验证、提交并推送，提交为 `fe5e8cd`。
- Phase 5 结构化输出增强已验证并提交，提交为 `04cf935`，随本次交接更新一起推送。
- 2026-10-09 最小真实 Structured Outputs 冒烟成功，无请求失败。
- Phase 6 已验证并提交，提交为 `c2fe1f9`，待随本次交接更新一起推送。
- Phase 7 已验证并提交，提交为 `0dd8add`，待随本次交接更新一起推送。
- Phase 8 已验证并提交，提交为 `fc919a9`，待随本次交接更新一起推送。

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

### 许可确认后的 Phase 3 增强

- 部署方确认 MediaCrawler 使用许可已取得。
- 以 Git submodule 固定引入上游：
  - 路径：`third_party/MediaCrawler`
  - commit：`098cae5a00023ad55f00ca9665d22d0f260e2ab2`
- 已在子模块内执行 `uv sync`。
- 已验证上游 `main.py --help` 可运行。
- 新增 `upstream_entry.py` 包装器：
  - 不修改上游源码。
  - 不绕过平台验证。
  - 映射 CDP 开关、端口、headless、登录态保存与请求休眠。
- 移除代码级 `license_accepted` 人工确认字段。
- 示例配置更新为 `allow_execution: true`。
- 保留固定 commit 校验，防止运行未审查版本。
- 新增 `run-mediacrawler` CLI：
  - 默认仅输出计划。
  - 显式 `--execute` 才执行。
  - 支持单关键词任务。
  - 支持配置内指定账号任务。
- 新增 `MediaCrawlerIntegrationService`：
  - 调用 Runner。
  - 自动发现任务目录 JSONL。
  - 自动加载为 `RawItem`。
  - 输出执行结果与加载结果。
- 主项目 Ruff / Mypy 排除 `third_party/`，避免格式化或检查上游源码。
- 已验证包装器在固定版本上游环境中可正常显示 CLI 帮助。
- 未启动浏览器、未执行真实平台采集。

### Phase 3 实现
### Phase 3 实现

- 将 `MediaCrawlerPlatform` 移入领域枚举，`RawItem.platform` 同时支持热搜平台与 MediaCrawler 平台。
- 新增 `MediaCrawlerTask`：
  - 稳定 UUIDv5 任务 ID。
  - 支持关键词检索与指定账号。
  - 支持搜索、创作者、详情采集类型。
  - 包含条目上限、评论上限、超时、工作区、输入文件与输出文件。
- 新增任务构建器：
  - `build_keyword_tasks`
  - `build_account_tasks`
  - 按启用层级、平台、关键词生成任务。
  - 按启用账号配置生成任务。
- 新增 `MediaCrawlerCommandPlan`：
  - 不使用 shell。
  - 使用参数数组。
  - 显式传入平台、登录方式、采集类型、关键词 / 账号 ID、条数、评论数、并发数与保存路径。
- 已根据上游 `cmd_arg/arg.py` 核对当前 CLI 参数。
- 新增 `MediaCrawlerRunner`：
  - 初版默认 `allow_execution=false`，只生成计划。
  - 许可确认后示例配置允许执行，但 CLI 仍需显式 `--execute`。
  - 实际执行前要求 40 位 commit SHA。
  - 校验第三方目录、入口文件与 Git HEAD。
  - 独立任务工作区。
  - stdout / stderr 落盘。
  - 超时 terminate / kill。
- 新增 JSONL 结果加载器：
  - 逐行解析。
  - 单行失败不丢弃整个文件。
  - 字段别名映射。
  - 时间统一 UTC。
  - 互动指标规范化。
  - 保留原始记录。
  - 生成统一 `RawItem`。
- 新增任务目录 JSONL 文件发现函数。
- 新增 CLI：
  - `plan-mediacrawler`
  - `load-mediacrawler`
- 增加人工合成 MediaCrawler JSONL fixture。
- 初版未引入上游源码；许可确认后已通过 submodule 固定引入。

### Phase 2 实现

- 新增 `opinion_monitor.models.enums`：
  - `HotSearchPlatform`
  - `SourceType`
- 新增 `opinion_monitor.models.raw.RawItem`：
  - 统一内部原始条目边界。
  - 当前支持 `hotsearch`。
  - 预留 `keyword_search` 与 `account`。
  - 时间字段强制带时区。
  - URL、排名、热度与 engagement 字段带范围校验。
- 新增 `opinion_monitor.collectors.interfaces`：
  - `HotSearchDocument`
  - `HotSearchParser`
  - `HotSearchParseError`
- 新增五个平台解析器：
  - 微博 HTML。
  - 百度 HTML。
  - 知乎 `js-initialData`。
  - 抖音 JSON。
  - bilibili JSON。
- 新增 `HotSearchHTTPClient`：
  - 配置化请求头。
  - 超时。
  - 重试。
  - 跳转跟随。
  - 公共 URL / SSRF 防护。
  - 根据 `security.allow_private_network` 控制内网地址策略。
  - 响应元信息保留。
- 新增 `HotSearchCollector`：
  - 顺序采集平台。
  - 单平台失败不影响后续平台。
  - 输出平台 outcome 与统一 items。
- 扩展 CLI：
  - `collect-hotsearch`
  - `--platform`
  - `--limit`
  - `--fail-on-error`
- 新增五个平台合成 fixture。
- 新增热搜采集中文文档 `docs/hotsearch.md`。
- 配置新增 `hotsearch.defaults.retry_backoff_seconds`。

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

Phase 2 验证结果：

- 测试：`33 passed`
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 22 source files`

2026-10-08 只读真实接口探针：

- bilibili：成功；确认真实结构为 `data.trending.list` 与 `heat_score`，解析器已修正。
- 百度：成功；确认置顶卡片、排名节点与热搜指数节点，解析器已修正。
- 抖音：HTTP 200 但响应体为空；不绕过平台限制。
- 微博：HTTP 200 但无可解析条目；可能要求登录态或返回验证页。
- 知乎：HTTP 403；不绕过平台限制。
- 真实热搜内容未写入仓库，fixture 继续使用人工构造数据。

以上结果为 Phase 1 中文基线后的完整验证结果。

Phase 3 验证结果：

- 测试：`47 passed`
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 32 source files`
- 上游依赖安装：`uv sync` 成功。
- 上游 CLI 帮助：`uv run main.py --help` 成功。
- 主系统包装器帮助：`upstream_entry.py --help` 成功。
- 单关键词任务计划：`run-mediacrawler` 未带 `--execute` 时输出 `skipped`，未启动浏览器。
- 子模块 HEAD：`098cae5a00023ad55f00ca9665d22d0f260e2ab2`，工作区干净。

## 2026-10-08 MediaCrawler 真实冒烟结果

### 关键词任务

- 平台：小红书。
- 关键词：`火灾`。
- 任务 ID：`20a7555f-7456-54b3-9cc7-7e23b4d6b9d2`。
- 二维码登录：用户已扫码成功。
- 登录态：已保存并复用成功。
- 上游输出：
  - 内容：20 条。
  - 评论：379 条。
- 按用户指定内容上限加载：5 条。
- 前 5 条对应评论数：
  - 66
  - 100
  - 44
  - 69
  - 100
- 单条评论数配置上限：100。
- 加载结果：`5 loaded, 0 failed`。
- 说明：MediaCrawler 当前关键词搜索会先返回单页 20 条，`crawler_max_notes_count=5` 不能在详情阶段硬截断；本次发现超过 5 条后立即人工停止，后续需要实现输出 watchdog 或上游补丁。

### 指定账号任务

- 平台：小红书。
- 账号配置：`provided_xhs_account`。
- 任务 ID：`d69d4e3d-097b-5c43-bb07-992769afe5ac`。
- 登录态：复用成功。
- 初始重试次数：2 次。
- 初始结果：两次均无 JSONL 输出。
- 初始上游错误：

  ```text
  Failed to parse creator URL: Expecting value: line 1 column 59065
  ```

- 初步判断：固定版本的小红书创作者主页 HTML 初始状态解析兼容性问题。
- 主系统已补充零输出判定：上游返回码为 0 但没有内容 JSONL 时，集成结果将标记为 `failed`。

### 小红书兼容性修复与账号复测

- 用户提供本地修复版本：
  - `/Users/rocky/WorkSpace/Personal/MediaCrawler`
- 已对比本地修复中的 `media_platform/xhs/extractor.py` 与固定子模块。
- 确认核心修复点：
  - 非贪婪匹配 `window.__INITIAL_STATE__`。
  - 支持 `undefined`、`NaN`、`Infinity`。
  - 支持 `new Set([])`。
  - 支持 `new Map([])`。
  - 解析失败返回 `None`，不抛出 JSON 异常。
- 新增主系统运行时兼容层：
  - `src/opinion_monitor/collectors/mediacrawler/xhs_compat.py`
- `upstream_entry.py` 启动时注入兼容层。
- 不修改 `third_party/MediaCrawler` 固定子模块源码。
- 新增兼容层测试：
  - JavaScript 字面量解析。
  - 非法状态返回 `None`。
  - creator 信息提取。
  - note 详情提取。
- 使用兼容层复测同一账号任务，结果成功：
  - 内容：5 条。
  - 评论：8 条。
  - 内容加载：`5 loaded, 0 failed`。
  - 任务状态：`succeeded`。
  - 任务耗时：约 45 秒。
  - 账号内容作者显示为 `澎***闻`。
- 复测输出：
  - `creator_contents_2026-10-08.jsonl`
  - `creator_comments_2026-10-08.jsonl`
- 账号任务前 5 条标题：
  1. 为改缓坡道，一名轮椅青年十年借力“移山”
  2. 安妮·卡森：一个“不可归类”的写作者
  3. 1.77亿港元成交！虞世南《积时帖》惊天复现
  4. 一文了解📖诺贝尔文学奖得主安妮·卡森
  5. 诺贝尔文学奖揭晓视频｜诗人安妮·卡森获奖
- 评论分布：
  - `6ac705d1000000001801aefc`: 1
  - `6ac78a3a000000001500a835`: 3
  - `6ac77f53000000001b01f426`: 4

### 冒烟后代码修正

- Runner 传给上游的 `--save_data_path` 改为绝对路径，确保输出落在主项目任务目录。
- 集成服务只把内容 JSONL 转换为 `RawItem`，不再把评论 JSONL 混入内容条目。
- `run-mediacrawler` 默认按 `max_items` 限制内容加载条数。
- 上游返回 0 但无内容 JSONL 时标记失败。
- 测试：`48 passed`。

## 2026-10-08/09 条数 Watchdog 实现

- 新增配置：
  - `mediacrawler.watchdog_enabled`
  - `mediacrawler.watchdog_poll_seconds`
- `MediaCrawlerCommandPlan` 记录 watchdog 配置。
- `MediaCrawlerRunResult` 记录：
  - `stopped_by_watchdog`
  - `watchdog_content_count`
- Runner 每次任务向包装器传递 `OPINION_MONITOR_MAX_ITEMS`。
- 新增小红书详情请求限流：
  - 在 `get_note_detail_async_task` 外层计数。
  - 达到 `max_items` 后后续详情任务返回 `None`。
  - 不再请求第 `max_items+1` 条详情。
  - 保留已采集条目的评论阶段。
- 新增通用输出 watchdog：
  - 轮询任务目录内容 JSONL。
  - 忽略评论 JSONL。
  - 忽略半写行与非法 JSON。
  - 完整内容记录数超过 `max_items` 时终止子进程。
  - 保留终止原因与实际计数。

### Watchdog 真实复测

- 平台：小红书。
- 关键词：`火灾`。
- 任务 ID：`20a7555f-7456-54b3-9cc7-7e23b4d6b9d2`。
- 输出目录：`data/media_crawler/watchdog_smoke_tasks/...`
- 配置：
  - 内容上限 5。
  - 单条评论上限 100。
- 结果：
  - 内容 5 条。
  - 评论 150 条。
  - 状态 `succeeded`。
  - `stopped_by_watchdog=false`。
- 结论：小红书详情请求限流已把内容限制在 5 条，且评论阶段未被截断。
- 测试：`54 passed`。

## Phase 4 实现

### 领域模型

- 新增 `CleanItem`：
  - 关联 RawItem。
  - 支持多个原始来源。
  - 保存规范化 URL 与 URL 哈希。
  - 保存 64 位 SimHash。
  - 保存标题哈希与内容哈希。
  - 保存初步规则分类、置信度与理由。
- 新增 `DiscardedItem`：
  - 保存丢弃原因与细节。
- 新增 `CommentRecord`：
  - 保存任务、平台、笔记、评论、父评论、作者、时间、点赞与原始 Payload。
- 新增 `ProcessingResult`：
  - 保存处理运行 ID。
  - 输入 / 接受 / 丢弃计数。
  - 清洗条目与丢弃明细。

### 清洗流水线

- Unicode NFKC 文本规范化。
- URL 规范化：
  - 小写 scheme / host。
  - 移除默认端口。
  - 归一化路径。
  - 查询参数排序。
  - 移除 fragment。
  - 移除追踪参数与小红书一次性 token。
- 发布时间过滤：
  - 默认超过 72 小时丢弃。
  - 缺失时间默认保留待人工复审。
  - 支持配置为缺失即丢弃。
- URL SHA-256 去重。
- 平台 + 外部 ID 去重。
- 64 位 SimHash：
  - token 特征。
  - Unicode 3-gram 特征。
- 文本相似度确认：
  - 标题阈值读取配置。
  - 标题 + 正文阈值读取配置。
  - 支持是否跨平台合并配置。
- 重复条目保留原始数据，并挂载到既有 CleanItem 来源列表。
- 规则分类读取 `rules.categories`。

### SQLite 持久化

- 新增 `SqliteStorage`：
  - WAL 模式。
  - 外键约束。
  - Schema 初始化。
  - 数据完整性统计。
- 新增表：
  - `media_crawler_tasks`
  - `media_crawler_runs`
  - `raw_items`
  - `comment_records`
  - `clean_items`
  - `clean_item_sources`
  - `processing_runs`
  - `processing_item_decisions`
- RawItem 与 CommentRecord 使用稳定 ID，重复入库幂等。
- `run-mediacrawler --execute` 会保存单次执行状态。
- 每个处理运行保存输入 / 接受 / 丢弃计数。
- 每个 RawItem 仅保留一条处理决策。
- 保留原始 Payload 与丢弃细节，支持审计。
- 当前显式限制 `storage.backend=sqlite`，未实现的 PostgreSQL 配置会报错。

### 评论证据加载

- 新增 `load_comment_jsonl`。
- 支持字段别名映射。
- 单行解析失败不会丢弃整个评论文件。
- 评论与内容分离加载，不再混入 RawItem。

### CLI

- 新增：
  - `init-db`
  - `ingest-mediacrawler-task`
  - `process-pending`
- `ingest-mediacrawler-task` 读取任务 `task.json`。
- 自动发现内容与评论 JSONL。
- 自动入库并执行清洗。
- 默认输出统计，不输出完整原始内容。
- `process-pending` 只处理尚无决策记录的 RawItem。

### Phase 4 真实数据验证

- 已入库关键词任务：
  - 任务 ID：`20a7555f-7456-54b3-9cc7-7e23b4d6b9d2`
  - 关键词：`火灾`
- 已入库指定账号任务：
  - 任务 ID：`d69d4e3d-097b-5c43-bb07-992769afe5ac`
  - 账号配置：`provided_xhs_account`
- 数据库：
  - `data/opinion_monitor.db`
- 结果：
  - RawItem：10。
  - CleanItem：6。
  - 评论：375。
  - 处理运行：2。
  - 处理决策：10。
- 关键词任务中 4 条超过 72 小时被丢弃，1 条保留。
- 指定账号任务 5 条均保留。
- `PRAGMA integrity_check` 结果：`ok`。
- `PRAGMA foreign_key_check` 无错误。
- 重复导入同一任务时：
  - `raw_inserted=0`
  - `comments_inserted=0`
  - pending 输入为 0
- 验证了入库与清洗幂等性。

### Phase 4 验证结果

- 测试：`66 passed`
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 45 source files`
- 新增文档：`docs/persistence-processing.md`

## Phase 5 实现

### LLM 领域模型

- 新增：
  - `GeoEvidence`
  - `SentimentEvidence`
  - `LLMUsage`
  - `LLMAnalysisResult`
  - `LLMPromptRequest`
  - `LLMAuditRecord`
  - `LLMAnalysisRun`
- 所有模型输出均通过 Pydantic 严格校验。
- 风险分数范围 0-100。
- 置信度与比例范围 0-1。
- 调用审计保留状态、耗时、尝试次数、错误与 Token 用量。

### Prompt 管理

- 新增 `config/prompts/`：
  - `classification.md`
  - `geo_extraction.md`
  - `sentiment_analysis.md`
  - `risk_assessment.md`
- Prompt 版本为文件内容 SHA-256 前 12 位。
- Prompt 输入使用结构化 JSON。
- Prompt 文件包含明确 JSON 输出约束。
- Prompt 不接收作者完整身份，只接收必要分析字段。

### OpenAI-compatible 客户端

- 使用 `httpx` 直接调用 Responses API：
  - 端点：`POST {OPENAI_BASE_URL}/responses`。
- 不依赖厂商 SDK。
- 支持环境变量读取：
  - base URL
  - API Key
  - model
- 支持超时与最大重试。
- 408 / 425 / 429 / 5xx / 传输错误可重试。
- `enable_structured_output=true` 时发送：
  - `text.format.type=json_schema`
  - `text.format.strict=true`
  - 每个任务独立 JSON Schema。
- 请求前递归校验严格 Schema 约束：
  - 对象 `additionalProperties=false`。
  - 全部字段进入 `required`。
  - 数组必须声明 `items`。
- 输出解析支持：
  - 顶层 SDK 风格 `output_text`。
  - `output[].content[].output_text` 拼接。
- 显式处理：
  - `status=incomplete` 与 `incomplete_details.reason`。
  - refusal。
  - 缺少输出文本。
  - 无效 JSON。
- Token 用量优先映射 `input_tokens` / `output_tokens` / `total_tokens`，并兼容 Chat Completions 旧字段。
- `enable_structured_output=false` 时仅作为兼容开关退回 `json_object`，不作为推荐模式。
- 宽松模式仍支持剥离 Markdown JSON 代码块。
- 不记录 API Key。
- 可注入 `httpx.MockTransport` 进行测试。

### LLM 分析服务

- 输入：
  - CleanItem。
  - 关联评论证据。
- 输出任务：
  - 预警资讯属性分类。
  - 地域实体提取。
  - 评论情感聚合。
  - 风险分数与建议。
- 评论输入最多 `llm.max_input_comments` 条，默认 100。
- 评论作者身份不进入 Prompt。
- 无评论时不调用情感模型，生成 unknown 证据并保留不确定性。
- 每个请求携带任务名与严格响应 Schema。
- `LLMPromptRequest` 新增：
  - `schema_name`
  - `response_schema`
- 情感 Schema 根据 `sentiment.categories` 动态生成：
  - `distribution` 的全部键。
  - `dominant_sentiment` 枚举。
- 模型输出缺少字段或校验失败时记录失败审计。
- LLM 分类与规则分类冲突时，LLM 结果独立保留，后续 Phase 6 评分时以 LLM 为准。

### SQLite 持久化

- Schema version 升级为 2。
- 新增表：
  - `llm_analysis_audits`
  - `llm_analysis_results`
- 审计保留每次调用历史。
- 结果按 CleanItem 幂等更新。
- 支持列出尚无 LLM 结果的 CleanItem。
- 支持按 CleanItem 聚合评论证据。

### CLI

- 新增：
  - `preview-llm-analysis`
  - `run-llm-analysis`
- `preview-llm-analysis` 只构建 Prompt 与响应 Schema，不调用模型。
- `run-llm-analysis` 默认仍只预览。
- 只有显式传入 `--execute` 才调用模型。
- 支持指定 CleanItem。
- 支持处理全部待分析条目。
- 支持 `--limit` 控制批量数量。
- 调用失败时 CLI 返回非零。

### 真实数据预览

- 使用本地真实 SQLite 数据：
  - CleanItem：`d87eb408-7518-53b6-9555-fa0d87ddd097`
  - 关联评论：72 条。
- 生成 Prompt：
  - classification：`4e6b46fe6969`
  - geo_extraction：`27b881c82c4e`
  - risk_assessment：`d2b7d4a50d32`
  - sentiment_analysis：`a4be50357479`（已补充 0-100 情感分标尺说明）
- 该预览未调用外部模型，未消耗 Token。
- 首次预览时 `llm_analysis_audits=0`、`llm_analysis_results=0`。
- 结构化输出增强后再次预览成功，四个任务的 `response_schema.required` 均完整输出。

### Phase 5 验证结果

- 测试：`87 passed`
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 52 source files`
- 新增文档：`docs/llm-analysis.md`
- Structured Outputs 增强提交：`04cf935`

### Phase 5 真实 Structured Outputs 冒烟

- 时间：2026-10-09，Asia/Shanghai。
- 使用 `.env` 中已配置的：
  - base URL
  - API Key
  - model
- 请求端点：`/responses`。
- 任务：`classification`。
- CleanItem：`d87eb408-7518-53b6-9555-fa0d87ddd097`。
- 请求格式：
  - `text.format.type=json_schema`
  - `text.format.strict=true`
- 结果：请求成功，服务端支持严格结构化输出。
- 模型输出：
  - category：`sudden_event`
  - confidence：`0.78`
  - reason：标题提及“火灾警报器”及其未响，涉及可能的火灾或消防警情，符合突发事件预警特征。
- Token 用量：
  - prompt/input：530
  - completion/output：124
  - total：654
- 无 HTTP 失败、拒答、未完成响应或 JSON 解析失败。
- 冒烟结果未写入 `llm_analysis_audits` / `llm_analysis_results`。

### Phase 5 完整四任务真实分析

- 时间：2026-10-09，Asia/Shanghai。
- CleanItem：`d87eb408-7518-53b6-9555-fa0d87ddd097`。
- 评论样本：72 条。
- 调用任务：classification、geo_extraction、risk_assessment、sentiment_analysis。
- 调用状态：`succeeded`。
- 调用次数：4。
- Token 用量：输入 5752，输出 1245，总计 6997。
- 输出摘要：
  - category：`sudden_event`
  - confidence：`0.82`
  - risk_score：`68`
  - dominant_sentiment：`positive`
- 无 HTTP 失败、拒答、未完成响应或 JSON 解析失败。
- 结果已写入本地库：`llm_analysis_audits=1`、`llm_analysis_results=1`。
- 首次输出把 `sentiment_score` 写成 `0.68`，属于 0-1 比例而非 0-100 分。
- 已修正：
  - `config/prompts/sentiment_analysis.md` 明确 `sentiment_score` 必须为 0-100。
  - Phase 6 评分服务对历史 `0 < score <= 1` 输出透明乘以 100，并记录 `raw_score` 与 `scale_normalized`。

## Phase 6 实现

### 领域模型

- 新增 `ScoreComponent`、`RiskAssessmentResult`、`StructuredOutputEvent`、`ScoringRunResult` 与领域枚举 `AlertLevel`。
- 每个分项保存原始分、权重、加权分、证据字段与解释文本。
- 研判结果保存：
  - LLM 最终分类与置信度。
  - 规则分类与置信度。
  - 分类冲突说明。
  - 六个分项。
  - 综合分数。
  - 预警级别与理由。
  - 人工复核状态与原因。
  - 风险理由、关键因素、信息缺口、建议动作与不确定性。
  - 模型名。
  - 评分配置版本。

### 评分服务

- 新增 `RiskScoringService`。
- 六个分项：
  1. 关键词属性分类。
  2. 来源权重。
  3. 热度。
  4. LLM 属性分类。
  5. 评论情感。
  6. LLM 风险建议。
- 权重总和不等于 1 时由配置 Schema 拒绝。
- 无热搜排名时使用 0 到 1,000,000 的确定性互动量对数基线。
- 有热搜排名时使用排名 60% + 互动 / 热度值 40%，排名基线为前 50 名。
- 指定账号优先使用账号配置权重；配置缺失时按普通社媒来源降权。
- 规则与 LLM 分类冲突时最终分类采用 LLM。
- 以下情况进入人工复核：
  - LLM 置信度低于 `scoring.manual_review_confidence`。
  - 规则分类与 LLM 分类冲突。
  - 缺少评论情感证据。
- 人工复核不会自动升级预警级别。

### 结构化事件

- `event_id` 由 CleanItem ID 派生，采用 UUIDv5，保证幂等。
- `trace_id` 当前使用 CleanItem ID。
- 包含标题、摘要、来源、平台、URL、最终分类、预警级别、综合分数、地域证据、情感摘要、关键风险因素、建议动作与不确定性说明。
- 不包含自然人不必要身份信息，可直接作为 Phase 7 钉钉输出输入。

### SQLite 持久化

- Schema version 从 2 升级为 3。
- 新增表：
  - `risk_assessments`
  - `structured_output_events`
- 支持列出已有 LLM 分析且尚无评分的 CleanItem。
- 支持按 CleanItem 获取 LLM 分析结果与关联 RawItem。
- 支持评分与结构化事件幂等更新。
- 已在本地真实 SQLite 数据库完成迁移验证。

### CLI

- 新增：
  - `preview-risk-assessment`
  - `run-risk-assessment`
- 支持指定 CleanItem。
- 支持 `--all` 与 `--limit`。
- 执行模式支持 `--force` 覆盖已有评分。
- 预览模式不写数据库。

### 真实数据评分验证

- CleanItem：`d87eb408-7518-53b6-9555-fa0d87ddd097`。
- 评分配置版本：`84da68fd98d1`。
- 最终分类：`sudden_event`。
- 综合得分：`66.5319`。
- 预警级别：`blue`。
- 分项分数：
  - keyword_category：60，加权 15.0。
  - source：60，加权 6.0。
  - heat：62.8794，加权 9.4319。
  - llm_category：82，加权 12.3。
  - sentiment：68，加权 10.2。
  - llm_risk：68，加权 13.6。
- 情感原始分为 0.68，评分层按历史 0-1 输出透明归一化为 68。
- 结构化事件 ID：`929819bf-7fbc-59a2-aba8-1756e79a05e5`。
- 当前真实库状态：`risk_assessments=1`、`structured_output_events=1`。

### Phase 6 验证结果

- 测试：`94 passed`
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 56 source files`
- 示例配置严格环境变量校验通过。
- 实现提交：`c2fe1f9`

## Phase 7 实现

### 钉钉契约调研

- 已阅读钉钉开放平台《Webhook 同步数据》文档。
- 确认：
  - 钉钉自动化 Webhook 接收外部系统推送的 JSON 对象。
  - 自动化流程可在钉钉内解析字段、格式化群消息并通知责任人或群组。
  - 可配置触发关键词，请求体需要包含该关键词。
  - “源数据解析”模式可接收钉钉机器人兼容消息结构，例如 Markdown。
  - Webhook 地址等同等密钥，不得泄露。
- 文档：
  - `https://open.dingtalk.com/document/connection/webhook-sync-data`

### 领域模型

- 新增：
  - `DingTalkAutomationPayload`
  - `DingTalkDeliveryRecord`
  - `DingTalkDeliveryAttempt`
  - `DingTalkDeliveryResult`
- 支持状态：
  - `running`
  - `succeeded`
  - `failed`
  - `dry_run`
  - `skipped`
- 记录：
  - Payload 哈希。
  - 完整脱敏 Payload。
  - HTTP 状态码。
  - 响应体。
  - 错误原因。
  - 尝试次数。
  - 是否即时。
  - 是否 dry-run。

### Payload 格式化

- 支持 `automation_json`：
  - `schema_version=1`
  - `source_system=opinion_monitor`
  - `event_type=opinion_monitor.alert`
  - `keyword=舆情预警`
  - `event_id`
  - `trace_id`
  - `dedup_key`
  - `occurred_at`
  - `data=StructuredOutputEvent`
- 支持 `markdown`：
  - 钉钉机器人兼容 `msgtype=markdown`。
  - 包含预警级别、标题、得分、分类、平台、摘要、情感、风险因素、建议动作、追踪 ID 与来源链接。
- 新增配置：
  - `output.dingtalk.trigger_keyword`
- 关键词会写入 automation JSON 与 Markdown 标题 / 正文。

### 安全策略

- 真实请求前校验 Webhook URL。
- 默认拒绝：
  - 内网地址。
  - 回环地址。
  - 链路本地地址。
  - 未指定地址。
  - 组播与保留地址。
- 禁止跟随重定向。
- 支持配置 SSL 校验开关。
- Payload 构建前脱敏：
  - 中国大陆手机号。
  - 18 位身份证号。
  - `author_id` / `user_id` 类字段。
- Webhook URL 只从环境变量读取，不写入 YAML、日志或 CLI 输出。

### Webhook 客户端

- 使用 `httpx` 直接 POST JSON。
- 支持超时。
- 支持最大重试次数与固定退避。
- 可重试状态：
  - 408 / 425 / 429 / 500 / 502 / 503 / 504。
- 其余 4xx 不重试。
- HTTP 2xx 后继续校验业务响应：
  - `errcode` 非零失败。
  - `code` 非零失败。
  - `success=false` 失败。
  - `status=failed/error/fail` 失败。
  - 空 Body、`ok`、`success` 纯文本可接受。
  - 非法 JSON 失败。
- 显式识别 `.env` 占位符 `replace-me`。

### SQLite 持久化

- Schema version 从 3 升级为 4。
- 新增：
  - `dingtalk_deliveries`
  - `dingtalk_delivery_attempts`
- `dingtalk_deliveries` 按事件幂等记录最终状态。
- `dingtalk_delivery_attempts` 保存每次真实请求或 dry-run。
- 重试尝试序号从既有 `attempt_count` 后继续。
- 只有 `status=succeeded` 表示真实成功，后续默认不重复投递。

### CLI

- 新增：
  - `preview-dingtalk-output`
  - `send-dingtalk-output`
- 支持：
  - `--event-id`
  - `--all`
  - `--limit`
  - `--include-queued`
  - `--force`
  - `--execute`
- 默认 dry-run。
- 只有显式 `--execute` 才发起真实 HTTP 请求。
- 预览不发送请求、不写台账。
- dry-run 会写投递状态与尝试记录。

### 真实结构化事件验证

- 已完成本地 SQLite Schema 3 -> 4 迁移。
- 事件：
  - `929819bf-7fbc-59a2-aba8-1756e79a05e5`
- 预警级别：
  - `blue`
- 发送模式：
  - `automation_json`
- Payload SHA-256：
  - `ad0fdba440ea00a373c8252801a8edf64293b06b90842b3db55ac1ba2a12c83d`
- Payload 顶层字段完整：
  - `schema_version`
  - `source_system`
  - `event_type`
  - `keyword`
  - `event_id`
  - `trace_id`
  - `dedup_key`
  - `occurred_at`
  - `data`
- dry-run 状态：成功。
- 已加入固定来源标识：
  - `source_system=opinion_monitor`
- 真实 Webhook 投递状态：成功。
  - HTTP 状态码：`200`
  - 响应：`{"data":true,"success":true}`
  - 尝试序号：`3`
- 当前真实库状态：
  - `dingtalk_deliveries=1`
  - `dingtalk_delivery_attempts=3`

### 真实 Webhook 冒烟结果

- 用户已将 `.env` 中的 `DINGTALK_AUTOMATION_WEBHOOK_URL` 替换为真实地址。
- 构造并发送了无敏感契约测试事件：
  - 标题：`舆情预警 Webhook 契约测试`
  - 事件 ID：`6ee2459c-aa47-42d9-9843-a00ab4c33293`
  - 级别：`orange`
  - 固定来源：`source_system=opinion_monitor`
  - 模式：`automation_json`
- 结果：
  - 状态：`succeeded`
  - HTTP 状态码：`200`
  - 响应：`{"data":true,"success":true}`
  - Payload SHA-256：`f1ede208d0a4c4f734d07fa62b5313a396cca923b045709a83dad609bfad89e8`
- 随后已发送真实结构化事件：
  - 事件 ID：`929819bf-7fbc-59a2-aba8-1756e79a05e5`
  - 预警级别：`blue`
  - 状态：`succeeded`
  - HTTP 状态码：`200`
  - 响应：`{"data":true,"success":true}`
- 结论：
  - Webhook URL 可用。
  - 触发关键词可用。
  - 钉钉服务端成功接收 JSON。
  - 业务响应 `success=true`。
  - 本地投递台账已写入真实成功状态。
  - 仍需在钉钉群 / 表格中人工确认 Workflow 最终展示效果。

### Phase 7 验证结果

- 测试：`105 passed`
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 60 source files`
- 示例配置严格环境变量校验通过。
- 实现提交：`0dd8add`
- 新增文档：`docs/dingtalk-output.md`

## Phase 8 实现

### 目标

Phase 8 补齐端到端编排与定时试运行：

```text
热搜采集
MediaCrawler 关键词采集
MediaCrawler 指定账号采集
        ↓
RawItem / CommentRecord 入库
        ↓
清洗 / 去重 / 规则分类
        ↓
LLM 分析
        ↓
综合评分 / 预警级别
        ↓
StructuredOutputEvent
        ↓
钉钉自动化产出
        ↓
调度与投递台账
```

### 领域模型

- 新增：
  - `PipelineStageResult`
  - `PipelineRunResult`
  - `ScheduledSource`
  - `SchedulerSourceRun`
  - `SchedulerCycleResult`
- 阶段状态：
  - `succeeded`
  - `partial`
  - `failed`
  - `skipped`
- 每个阶段保存：
  - 阶段名。
  - 状态。
  - 开始 / 结束时间。
  - 耗时。
  - 计数与证据。
  - 错误原因。

### PipelineService

- 新增统一端到端服务：
  - `src/opinion_monitor/orchestration/pipeline.py`
- 支持阶段：
  1. 热搜采集与 RawItem 入库。
  2. MediaCrawler 采集、内容 / 评论 JSONL 入库。
  3. 统一清洗。
  4. LLM 四任务分析。
  5. 综合评分与结构化事件。
  6. 钉钉产出。
- 热搜阶段单平台失败不影响其他平台。
- 全部启用热搜平台失败才标记阶段失败。
- 部分成功 / 部分失败标记 `partial`。
- MediaCrawler 任务先入库，不在单任务内立即清洗，避免并发调度来源重复处理 pending 数据。
- 后续由统一清洗阶段集中处理全部 pending RawItem。
- LLM 阶段逐条保留成功 / 失败审计。
- 评分阶段只处理已有 LLM 分析且尚无评分的 CleanItem。
- 钉钉阶段默认只处理启用级别；`--include-queued` 时包含蓝色等非即时事件。
- 预览模式不访问任何外部服务。
- 真实模式必须显式传入 `--execute`。

### SchedulerService

- 新增调度服务：
  - `src/opinion_monitor/orchestration/scheduler.py`
- 调度来源：
  - `hotsearch:<platform>`
  - `keyword_search:<level_name>`
  - `account:<account_config_id>`
- 每个来源独立计算：
  - interval。
  - jitter 最小值。
  - jitter 最大值。
  - 下次执行时间。
- 热搜平台支持完整覆盖 interval / jitter。
- 采集来源按 `scheduler.max_concurrent_tasks` 控制并发。
- 每个来源受 `scheduler.task_timeout_seconds` 超时约束。
- 采集层完成后统一执行一次后续处理，避免并发清洗重复。
- `missed_task_policy=skip/run_once` 当前均只补跑一次，不连续追赶历史错过的多个周期。

### SQLite 持久化

- Schema version 从 4 升级为 5。
- 新增表：
  - `scheduler_state`
  - `scheduler_runs`
- `scheduler_state` 按来源保存：
  - source_key。
  - source_kind。
  - last_run_at。
  - next_run_at。
  - updated_at。
- `scheduler_runs` 保存：
  - 调度运行 ID。
  - 周期 ID。
  - 来源。
  - 状态。
  - 开始 / 结束时间。
  - 错误。
  - 完整 Pipeline 结果 JSON。
- 已在本地真实 SQLite 数据库完成 Schema 4 -> 5 迁移。

### CLI：run-pipeline

- 新增：
  - `run-pipeline`
- 支持：
  - `--source all|hotsearch|media`
  - `--hotsearch-platform`
  - `--media-platform`
  - `--keyword-level`
  - `--account-config-id`
  - `--media-limit`
  - `--llm-limit`
  - `--output-limit`
  - `--skip-processing`
  - `--skip-llm`
  - `--skip-scoring`
  - `--skip-output`
  - `--include-queued`
  - `--fail-fast`
  - `--execute`
- 默认不访问外部服务。

### CLI：run-scheduler

- 新增：
  - `run-scheduler`
- 支持：
  - `--max-cycles`
  - `--forever`
  - `--idle-seconds`
  - `--media-limit`
  - `--llm-limit`
  - `--output-limit`
  - `--skip-processing`
  - `--skip-llm`
  - `--skip-scoring`
  - `--skip-output`
  - `--include-queued`
  - `--fail-fast`
  - `--execute`
- 默认单周期。
- 默认不访问外部服务，但会推进调度状态以验证下次执行时间。
- `--forever` 时按空闲时间常驻运行。

### 本地安全预览

已执行：

```bash
opinion-monitor --config config/config.local.yaml run-pipeline
```

结果：

- Run ID：`64aff2e8-04f7-4f95-b8c0-49da75d54517`
- executed：`false`
- status：`succeeded`
- 阶段：
  - hotsearch：skipped，未访问 5 个平台。
  - mediacrawler：skipped，未启动 1 个账号任务。
  - processing：无 pending 输入。
  - llm_analysis：skipped，待分析 5 条，未调用模型。
  - risk_scoring：skipped，无待评分条目。
  - dingtalk_output：skipped，无待投递事件。
- 未访问热搜、MediaCrawler、LLM 或钉钉。

### 调度器本地试运行

已执行：

```bash
opinion-monitor --config config/config.local.yaml run-scheduler
```

结果：

- Cycle ID：`65813053-22d2-45de-83b6-3c2b85b530a4`
- executed：`false`
- status：`succeeded`
- 到期来源：6 个。
  - hotsearch:weibo
  - hotsearch:baidu
  - hotsearch:zhihu
  - hotsearch:douyin
  - hotsearch:bilibili
  - account:provided_xhs_account
- 后续处理状态：succeeded。
- 保存：
  - `scheduler_state=6`
  - `scheduler_runs=6`
- 第二次执行时无来源到期：
  - source_run_count=0
  - idle_seconds 约为 280 秒
- 未访问任何外部服务。

### Phase 8 验证结果

- 测试：`111 passed`
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 65 source files`
- 示例配置严格环境变量校验通过。
- 本地 SQLite：
  - Schema version=5。
  - `scheduler_state=6`。
  - `scheduler_runs=6`。
- 实现提交：`fc919a9`
- 新增文档：`docs/end-to-end.md`

## 当前阻塞点

1. 尚未执行 Phase 8 的全量真实外部请求试运行。
2. 尚未在钉钉群 / 表格中人工确认自动化 Workflow 最终展示效果。
3. 尚未实现 PostgreSQL 存储。
4. 尚未对其余 5 条 CleanItem 执行完整 LLM 分析与评分。
5. 情感分类体系仍是候选方案，等待业务确认。

## 紧接着的后续步骤

1. 执行一次小规模 `run-pipeline --execute` 真实端到端试运行。
2. 执行一次 `run-scheduler --execute` 真实调度周期。
3. 用户在钉钉群 / 表格中确认无敏感契约测试事件与真实蓝色事件是否按预期展示。
4. 如展示字段缺失，调整钉钉 Workflow 映射。
5. 评估是否补齐其余 5 条 CleanItem 的 LLM 分析与评分。

## 阶段实施计划

1. **Phase 1**：配置模型、环境变量展开、日志与 CLI。已完成。
2. **Phase 2**：热搜采集器与解析 fixture。已完成，并完成真实接口探针与 bilibili / 百度解析修正。
3. **Phase 3**：MediaCrawler 任务构建、执行、结果加载与平台映射。固定版本、单任务执行、关键词真实冒烟已完成；账号采集待解析问题解决。
4. **Phase 4**：清洗、日期过滤、URL / 内容去重与状态仓储。已完成。
5. **Phase 5**：OpenAI 兼容 Responses API 与严格结构化输出。基线、最小冒烟与一条完整四任务真实分析已完成。
6. **Phase 6**：评分、预警级别分类与可解释记录。已完成一条真实数据端到端评分入库。
7. **Phase 7**：钉钉自动化输出、重试与投递台账。代码基线、无敏感契约测试与真实事件端到端投递均已完成。
8. **Phase 8**：端到端与定时试运行。编排、调度、CLI、台账与本地安全试运行已完成，真实全量试运行待执行。

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
