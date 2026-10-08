# 交接记录（HANDOFF）

## 当前目标

建立舆情监测系统的私有版本控制仓库与中文设计基线，然后按阶段实现采集、清洗、研判、评分与钉钉产出能力。部署方已确认取得 MediaCrawler 使用许可；Phase 3 已固定引入上游子模块，完成任务构建、隔离执行、上游配置映射、单任务 CLI 与 JSONL 自动加载。尚未执行真实采集，因为缺少具体关键词 / 账号范围与平台登录态。

## 更新时间

2026-10-08，Asia/Shanghai

## 仓库状态

- 工作目录：`/Users/rocky/WorkSpace/GA/test-crawler`
- 远端仓库：`git@github.com:Rocky77JHxu/public-opinion-monitor.git`
- 本地与远端主分支均为 `main`。
- 原英文基线提交已从 `main` 历史中回撤。
- 当前基线为无旧历史的中文提交。
- Phase 1 已提交推送，提交为 `76da3d9`。
- Phase 2 已验证、提交并推送，提交为 `00306f1`，后续解析修复提交为 `9eb051e`。
- Phase 3 主系统侧基线已提交为 `efb8828`。
- 许可确认后的固定版本接入与执行能力增强已完成，待提交推送。

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
- 重试次数：2 次。
- 结果：两次均无 JSONL 输出。
- 上游错误：

  ```text
  Failed to parse creator URL: Expecting value: line 1 column 59065
  ```

- 初步判断：固定版本的小红书创作者主页 HTML 初始状态解析兼容性问题，或该一次性 `xsec_token` / 页面响应不可解析。
- 已按约定在第二次失败后停止，不继续加压。
- 主系统已补充零输出判定：上游返回码为 0 但没有内容 JSONL 时，集成结果将标记为 `failed`。
- 后续需要用户提供新的账号主页链接，或在授权下为固定版本添加兼容性补丁后重试。

### 冒烟后代码修正

- Runner 传给上游的 `--save_data_path` 改为绝对路径，确保输出落在主项目任务目录。
- 集成服务只把内容 JSONL 转换为 `RawItem`，不再把评论 JSONL 混入内容条目。
- `run-mediacrawler` 默认按 `max_items` 限制内容加载条数。
- 上游返回 0 但无内容 JSONL 时标记失败。
- 测试：`48 passed`。

## 当前阻塞点

1. MediaCrawler 关键词真实冒烟已成功；账号采集仍因上游创作者页解析失败，需要新链接或兼容性补丁。
2. 尚未测试钉钉自动化 Webhook 的真实 Payload 契约。
3. 尚未实现任务状态与原始数据持久化。
4. 尚未实现常驻调度器。
5. 情感分类体系仍是候选方案，等待业务确认。

## 紧接着的后续步骤

1. 为 MediaCrawler 任务增加内容条数 watchdog，防止单页 20 条导致超出配置上限。
2. 获取新的小红书账号主页链接，或评估是否为固定版本添加创作者页解析兼容性补丁。
3. 进入 Phase 4：任务状态、原始条目与评论证据持久化。
4. 实现日期过滤、URL 规范化、URL 去重与内容相似度去重。
5. 用无敏感测试 Payload 验证钉钉自动化 Webhook。

## 阶段实施计划

1. **Phase 1**：配置模型、环境变量展开、日志与 CLI。已完成。
2. **Phase 2**：热搜采集器与解析 fixture。已完成，并完成真实接口探针与 bilibili / 百度解析修正。
3. **Phase 3**：MediaCrawler 任务构建、执行、结果加载与平台映射。固定版本、单任务执行、关键词真实冒烟已完成；账号采集待解析问题解决。
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
