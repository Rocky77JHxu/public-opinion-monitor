# 舆情监测系统

本项目是一个面向受控合规场景的舆情采集、标准化、研判、评分与通知流水线。当前项目处于 **Phase 2：热搜采集基线** 阶段，尚未接入 MediaCrawler，也未启动常驻爬取任务。

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
- 五个平台的合成 fixture 与回归测试。

尚未实现：

- 常驻调度器。
- 原始数据持久化。
- MediaCrawler 集成。
- 清洗与去重。
- LLM 分析模块。
- 评分流水线。
- 钉钉 Webhook 客户端。

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
```

本地测试前先复制环境变量模板：

```bash
cp .env.example .env
```

配置示例位于 `config/config.example.yaml`。本地私密配置应复制为 `config/config.local.yaml`，该文件已被 Git 忽略。详细规则见 [配置与 CLI 使用说明](docs/configuration.md)。
