# 配置与 CLI 使用说明

## 配置文件

默认示例配置：

```text
config/config.example.yaml
```

本地配置建议复制为：

```text
config/config.local.yaml
```

`config.local.yaml` 已被 Git 忽略。不要把真实 Webhook、API Key、数据库 DSN 或账号凭证提交到仓库。

## 配置加载流程

配置加载顺序如下：

1. 读取 YAML 文件。
2. 拒绝重复 YAML 键。
3. 递归展开字符串中的环境变量引用。
4. 使用 Pydantic Schema 校验字段、枚举、范围和交叉约束。
5. CLI 日志级别与日志格式参数可覆盖配置文件中的 `app.log_level` 与 `app.log_format`。

## 环境变量引用

支持两种方式。

### 1. 内联展开

适用于字符串字段：

```yaml
app:
  name: ${APP_NAME:-opinion-monitor}
```

支持：

```text
${VAR}
${VAR:-default}
```

如果变量不存在且没有默认值，配置加载会失败。

### 2. 显式引用字段

示例配置使用 `*_env` 字段保存环境变量名：

```yaml
llm:
  base_url_env: OPENAI_BASE_URL
  api_key_env: OPENAI_API_KEY
  model_env: OPENAI_MODEL

output:
  dingtalk:
    webhook_url_env: DINGTALK_AUTOMATION_WEBHOOK_URL
```

这种方式避免把秘密值混入 YAML。默认情况下，这些变量缺失不会阻止 Schema 校验，便于开发环境启动；生产或发布前检查应使用 `--strict-env`。

## 环境变量文件

可以传入 `.env` 格式文件：

```bash
opinion-monitor --env-file .env inspect-env
```

支持：

```text
# 注释
TEST_ONE=value-one
export TEST_TWO='value two'
```

规则：

- 环境变量文件只用于当前命令进程，不写回 shell。
- 进程内已有环境变量优先于 `.env` 文件。
- 环境变量文件不应提交到 Git。

## CLI 命令

全局参数需要放在子命令之前。

### 查看版本

```bash
uv run opinion-monitor --version
```

### 校验配置

```bash
uv run opinion-monitor validate-config
```

指定本地配置：

```bash
uv run opinion-monitor --config config/config.local.yaml validate-config
```

严格要求所有显式引用的环境变量都存在：

```bash
uv run opinion-monitor --env-file .env validate-config --strict-env
```

### 查看环境变量引用

```bash
uv run opinion-monitor inspect-env
```

输出包含：

- 配置文件路径。
- 环境变量文件路径。
- 全部 `*_env` 引用。
- 当前缺失的变量。

### 查看脱敏配置

```bash
uv run opinion-monitor show-config --format json
uv run opinion-monitor show-config --format yaml
```

输出前会递归遮蔽以下类型的键：

- API Key。
- Token。
- Secret。
- Password。
- Credential。
- DSN。
- Webhook URL。

以 `_env` 结尾的字段只包含变量名，不包含秘密值，因此会正常显示。

## LLM 分析配置

LLM 密钥只通过环境变量读取：

```yaml
llm:
  base_url_env: OPENAI_BASE_URL
  api_key_env: OPENAI_API_KEY
  model_env: OPENAI_MODEL
  enable_structured_output: true
  max_input_comments: 100
```

默认建议先使用：

```bash
uv run opinion-monitor preview-llm-analysis
```

该命令只构建 Prompt 与响应 Schema，不调用模型。只有在 `run-llm-analysis` 上显式追加 `--execute` 才会请求 OpenAI-compatible Responses API。

`enable_structured_output: true` 是推荐值，会发送 `text.format.type=json_schema` 与 `strict=true`。`false` 只用于兼容不支持 Structured Outputs 的服务，退回 `json_object`。

## MediaCrawler 安全开关

MediaCrawler 使用许可已确认。示例配置允许显式执行，但仍要求 CLI 传入 `--execute`：

```yaml
mediacrawler:
  allow_execution: true
  pinned_ref: "098cae5a00023ad55f00ca9665d22d0f260e2ab2"
```

Runner 会校验 `third_party/MediaCrawler` 的实际 `HEAD` 与 `pinned_ref` 是否一致。版本不匹配时拒绝执行。

MediaCrawler 条数保护：

```yaml
mediacrawler:
  watchdog_enabled: true
  watchdog_poll_seconds: 0.25
```

- 小红书任务会在详情请求层按 `max_items` 计数，达到上限后跳过后续详情，并保留已采集条目的评论阶段。
- 通用 watchdog 会轮询内容 JSONL；如果完整记录数超过 `max_items`，立即终止上游子进程。
- 评论文件不参与内容条数统计。
- 半写行和非法 JSON 不计入 watchdog 触发阈值。

## 日志

配置项：

```yaml
app:
  log_level: INFO
  log_format: console
```

支持：

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

格式支持：

```text
console
json
```

命令行覆盖：

```bash
uv run opinion-monitor --log-level DEBUG --log-format json inspect-env
```

日志中禁止输出：

- Cookie。
- API Key。
- 访问令牌。
- 数据库 DSN。
- 完整 Webhook URL。
- 身份证号。
- 其他未脱敏个人信息。

## Schema 校验重点

当前配置模型会检查：

- 未知字段。
- 重复 YAML 键。
- IANA 时区有效性。
- 调度间隔与浮动窗口关系。
- 权重和阈值范围。
- 评分权重总和必须为 1。
- 预警阈值必须满足 `archive < blue < orange < red`。
- 热搜 HTTP 重试次数与等待时间。
- 情感类别与权重键完全一致。
- 平台列表重复项。
- 关键词空值与重复项。
- 钉钉输出级别完整性。
