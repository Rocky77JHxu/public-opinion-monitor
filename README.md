# 舆情监测系统

本项目是一个面向受控合规场景的舆情采集、标准化、研判、评分与通知流水线。当前项目处于 **Phase 0：仓库与设计基线** 阶段，尚未实现生产级采集器，也未启动任何实际爬取任务。

## 系统定位

系统规划为五个层次：

1. **采集层**：定时采集热搜、按关键词检索、按已授权账号检索。
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
- [合规与安全要求](docs/compliance.md)

## 当前状态

已完成：

- 本地 Git 仓库与远端私有仓库基线。
- Python / uv 项目配置。
- 基础包入口与最小测试。
- 示例 YAML 配置。
- 中文架构、数据流、数据模型、评分、集成与合规文档。
- `HANDOFF.md` 跨对话交接记录。

尚未实现：

- 热搜采集适配器。
- MediaCrawler 集成。
- 数据库迁移与状态仓储。
- LLM 分析模块。
- 评分流水线。
- 钉钉 Webhook 客户端。
- 生产级调度器。

## 开发环境

项目使用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境：

```bash
uv sync
uv run opinion-monitor --version
uv run pytest
```

本地测试前先复制环境变量模板：

```bash
cp .env.example .env
```

配置示例位于 `config/config.example.yaml`。本地私密配置应复制为 `config/config.local.yaml`，该文件已被 Git 忽略。

## 重要范围与合规说明

本系统必须在完成法律与合规审批后才能部署。采集范围必须限于部署方被授权的目的和来源，遵守适用法律与平台条款，控制请求频率，并避免不必要地采集或留存个人信息。

MediaCrawler 上游许可证面向非商业学习用途。政府或生产环境使用前，必须单独完成许可证、平台条款与适用法律审查，并获得必要授权。
