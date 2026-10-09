#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

usage() {
  cat <<'USAGE'
舆情监测系统端到端测试脚本

用法：
  scripts/e2e-test.sh --execute

默认行为：
  1. 执行代码质量检查与全量测试；
  2. 生成隔离测试配置和 SQLite 数据库；
  3. 只运行本地安全预览，不访问外部服务。

真实端到端测试：
  scripts/e2e-test.sh --execute

常用参数：
  --execute                 执行真实热搜、MediaCrawler、LLM 与钉钉请求
  --preview                 执行本地安全预览；这是默认模式
  --generate-only           只生成隔离测试配置，不运行流水线
  --skip-tests              跳过 Ruff / Mypy / Pytest 基线检查
  --skip-account            跳过指定账号来源
  --all-hotsearch           尝试全部已启用热搜平台
  --hotsearch-platform P    指定热搜平台，可重复；默认 baidu 和 bilibili
  --keyword KEYWORD         关键词，默认：火灾
  --account-id ID           指定账号配置 ID，默认：provided_xhs_account
  --hotsearch-limit N       每个热搜平台进入链路的条数，默认 1
  --media-limit N           MediaCrawler 任务加载条数，默认 1
  --llm-limit N             LLM 分析条数上限，默认 10
  --output-limit N          钉钉产出条数上限，默认 10
  --llm-retries N           LLM 429 后的补跑次数，默认 3
  --retry-delay SECONDS     补跑前等待秒数，默认 60
  --config PATH             源配置文件，默认 config/config.local.yaml
  --env-file PATH           环境变量文件，默认 .env
  --root PATH               指定隔离测试目录；默认自动生成
  -h, --help                显示帮助

示例：
  # 安全预览
  scripts/e2e-test.sh

  # 真实完整端到端测试
  scripts/e2e-test.sh --execute

  # 使用稳定热搜平台，降低外部平台波动影响
  scripts/e2e-test.sh --execute \\
    --hotsearch-platform baidu \\
    --hotsearch-platform bilibili

  # 跳过指定账号，仅测试热搜与关键词
  scripts/e2e-test.sh --execute --skip-account
USAGE
}

die() {
  printf '\n[ERROR] %s\n' "$*" >&2
  exit 1
}

info() {
  printf '\n==> %s\n' "$*"
}

MODE="preview"
SKIP_TESTS=0
SKIP_ACCOUNT=0
ALL_HOTSEARCH=0
KEYWORD="火灾"
ACCOUNT_ID="provided_xhs_account"
HOTSEARCH_LIMIT=1
MEDIA_LIMIT=1
LLM_LIMIT=10
OUTPUT_LIMIT=10
LLM_RETRIES=3
RETRY_DELAY=60
SOURCE_CONFIG="$PROJECT_ROOT/config/config.local.yaml"
ENV_FILE="$PROJECT_ROOT/.env"
ROOT_OPTION=""
HOTSEARCH_PLATFORMS=(baidu bilibili)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute)
      MODE="execute"
      shift
      ;;
    --preview)
      MODE="preview"
      shift
      ;;
    --generate-only)
      MODE="generate-only"
      shift
      ;;
    --skip-tests)
      SKIP_TESTS=1
      shift
      ;;
    --skip-account)
      SKIP_ACCOUNT=1
      shift
      ;;
    --all-hotsearch)
      ALL_HOTSEARCH=1
      HOTSEARCH_PLATFORMS=()
      shift
      ;;
    --hotsearch-platform)
      [[ $# -ge 2 ]] || die "--hotsearch-platform 需要参数"
      HOTSEARCH_PLATFORMS+=("$2")
      shift 2
      ;;
    --keyword)
      [[ $# -ge 2 ]] || die "--keyword 需要参数"
      KEYWORD="$2"
      shift 2
      ;;
    --account-id)
      [[ $# -ge 2 ]] || die "--account-id 需要参数"
      ACCOUNT_ID="$2"
      shift 2
      ;;
    --hotsearch-limit)
      [[ $# -ge 2 ]] || die "--hotsearch-limit 需要参数"
      HOTSEARCH_LIMIT="$2"
      shift 2
      ;;
    --media-limit)
      [[ $# -ge 2 ]] || die "--media-limit 需要参数"
      MEDIA_LIMIT="$2"
      shift 2
      ;;
    --llm-limit)
      [[ $# -ge 2 ]] || die "--llm-limit 需要参数"
      LLM_LIMIT="$2"
      shift 2
      ;;
    --output-limit)
      [[ $# -ge 2 ]] || die "--output-limit 需要参数"
      OUTPUT_LIMIT="$2"
      shift 2
      ;;
    --llm-retries)
      [[ $# -ge 2 ]] || die "--llm-retries 需要参数"
      LLM_RETRIES="$2"
      shift 2
      ;;
    --retry-delay)
      [[ $# -ge 2 ]] || die "--retry-delay 需要参数"
      RETRY_DELAY="$2"
      shift 2
      ;;
    --config)
      [[ $# -ge 2 ]] || die "--config 需要参数"
      SOURCE_CONFIG="$2"
      shift 2
      ;;
    --env-file)
      [[ $# -ge 2 ]] || die "--env-file 需要参数"
      ENV_FILE="$2"
      shift 2
      ;;
    --root)
      [[ $# -ge 2 ]] || die "--root 需要参数"
      ROOT_OPTION="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      die "未知参数：$1"
      ;;
  esac
done

[[ -x "$PROJECT_ROOT/.venv/bin/opinion-monitor" ]] || die "未找到 .venv/bin/opinion-monitor，请先执行 uv sync"
[[ -f "$SOURCE_CONFIG" ]] || die "源配置不存在：$SOURCE_CONFIG"

if [[ "$MODE" == "execute" ]]; then
  [[ -f "$ENV_FILE" ]] || die "环境变量文件不存在：$ENV_FILE"
fi

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  info "执行 Ruff / Mypy / Pytest 基线检查"
  "$PROJECT_ROOT/.venv/bin/ruff" format --check src tests
  "$PROJECT_ROOT/.venv/bin/ruff" check src tests
  "$PROJECT_ROOT/.venv/bin/mypy" src tests
  "$PROJECT_ROOT/.venv/bin/pytest"
fi

if [[ "$MODE" == "execute" ]]; then
  info "检查环境变量是否已配置且不是占位符"
  ENV_FILE="$ENV_FILE" "$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import os
from pathlib import Path

from opinion_monitor.config.loader import load_env_file

values = load_env_file(Path(os.environ["ENV_FILE"]))
required = [
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "DINGTALK_AUTOMATION_WEBHOOK_URL",
]
missing = [key for key in required if not values.get(key)]
placeholders = [key for key in required if values.get(key) == "replace-me"]
if missing or placeholders:
    raise SystemExit(
        "环境变量未就绪："
        f"missing={missing}, placeholders={placeholders}"
    )
print("环境变量检查通过；未输出任何密钥。")
PY
fi

if [[ -n "$ROOT_OPTION" ]]; then
  E2E_ROOT="$ROOT_OPTION"
else
  E2E_ROOT="$PROJECT_ROOT/data/e2e/script-$(date +%Y%m%d-%H%M%S)-$$"
fi

[[ ! -e "$E2E_ROOT" ]] || die "测试目录已存在：$E2E_ROOT"
mkdir -p "$E2E_ROOT"

info "生成隔离端到端测试配置：$E2E_ROOT/config.yaml"

E2E_ROOT="$E2E_ROOT" \
SOURCE_CONFIG="$SOURCE_CONFIG" \
KEYWORD="$KEYWORD" \
ACCOUNT_ID="$ACCOUNT_ID" \
SKIP_ACCOUNT="$SKIP_ACCOUNT" \
HOTSEARCH_PLATFORMS="${HOTSEARCH_PLATFORMS[*]}" \
ALL_HOTSEARCH="$ALL_HOTSEARCH" \
HOTSEARCH_LIMIT="$HOTSEARCH_LIMIT" \
"$PROJECT_ROOT/.venv/bin/python" - <<'PY'
import os
from pathlib import Path

import yaml

root = Path(os.environ["E2E_ROOT"])
source = Path(os.environ["SOURCE_CONFIG"])
keyword = os.environ["KEYWORD"]
account_id = os.environ["ACCOUNT_ID"]
skip_account = os.environ["SKIP_ACCOUNT"] == "1"
all_hotsearch = os.environ["ALL_HOTSEARCH"] == "1"
hotsearch_limit = int(os.environ["HOTSEARCH_LIMIT"])

config = yaml.safe_load(source.read_text(encoding="utf-8"))

if not keyword.strip():
    raise SystemExit("关键词不能为空")
if not config.get("mediacrawler", {}).get("allow_execution", False):
    raise SystemExit("源配置 mediacrawler.allow_execution 必须为 true")

config["app"]["environment"] = "testing"
config["storage"]["sqlite"]["path"] = str(root / "opinion_monitor.db")

config["hotsearch"]["defaults"]["enabled"] = True
config["hotsearch"]["defaults"]["max_items_per_platform"] = hotsearch_limit

config["mediacrawler"]["save_path"] = str(root / "media_crawler")
config["mediacrawler"]["task_dir"] = str(root / "media_crawler/tasks")
config["mediacrawler"]["max_comments_per_note"] = 5
config["mediacrawler"]["task_timeout_seconds"] = 900

config["keyword_search"]["defaults"]["enabled"] = True
config["keyword_search"]["defaults"]["max_items_per_keyword"] = 1
config["keyword_search"]["defaults"]["max_comments_per_item"] = 5
for level_name, level in config["keyword_search"]["levels"].items():
    level["enabled"] = level_name == "level_1"
config["keyword_search"]["levels"]["level_1"]["platforms"] = ["xhs"]
config["keyword_search"]["levels"]["level_1"]["keywords"] = [keyword]

config["account_search"]["defaults"]["enabled"] = not skip_account
config["account_search"]["defaults"]["max_items_per_account"] = 1
config["account_search"]["defaults"]["max_comments_per_item"] = 5
if not skip_account:
    accounts = config["account_search"].get("accounts", {})
    if account_id not in accounts:
        raise SystemExit(f"指定账号不存在：{account_id}")
    accounts[account_id]["max_items"] = 1

config["processing"]["date_filter"]["max_age_hours"] = 8760

config["llm"]["max_input_comments"] = 5
config["llm"]["timeout_seconds"] = 90
config["llm"]["max_output_tokens"] = 2000

for level in config["output"]["dingtalk"]["levels"].values():
    level["enabled"] = True
config["output"]["dingtalk"]["dry_run"] = True

if not all_hotsearch:
    platforms = os.environ["HOTSEARCH_PLATFORMS"].split()
    platform_config = config["hotsearch"]["platforms"]
    for platform in platforms:
        if platform not in platform_config:
            raise SystemExit(f"热搜平台不存在：{platform}")
        if not platform_config[platform].get("enabled", False):
            raise SystemExit(f"热搜平台未启用：{platform}")

config_path = root / "config.yaml"
config_path.write_text(
    yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)

metadata = {
    "root": str(root),
    "source_config": str(source),
    "keyword": keyword,
    "account_id": None if skip_account else account_id,
    "skip_account": skip_account,
    "all_hotsearch": all_hotsearch,
    "hotsearch_platforms": [] if all_hotsearch else platforms,
    "hotsearch_limit": hotsearch_limit,
}
(root / "metadata.json").write_text(
    __import__("json").dumps(metadata, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(f"已生成：{config_path}")
PY

CONFIG="$E2E_ROOT/config.yaml"
DATABASE="$E2E_ROOT/opinion_monitor.db"

info "严格校验隔离测试配置"
"$PROJECT_ROOT/.venv/bin/opinion-monitor" \
  --config "$CONFIG" \
  --env-file "$ENV_FILE" \
  validate-config \
  --strict-env

if [[ "$MODE" == "generate-only" ]]; then
  info "generate-only 模式结束"
  printf 'E2E_ROOT=%s\nCONFIG=%s\nDATABASE=%s\n' "$E2E_ROOT" "$CONFIG" "$DATABASE"
  exit 0
fi

PIPELINE_ARGS=(
  --config "$CONFIG"
  run-pipeline
  --source all
  --hotsearch-limit "$HOTSEARCH_LIMIT"
  --media-limit "$MEDIA_LIMIT"
  --llm-limit "$LLM_LIMIT"
  --output-limit "$OUTPUT_LIMIT"
  --include-queued
)

if [[ "$ALL_HOTSEARCH" -eq 0 ]]; then
  for platform in "${HOTSEARCH_PLATFORMS[@]}"; do
    PIPELINE_ARGS+=("--hotsearch-platform" "$platform")
  done
fi

if [[ "$MODE" == "preview" ]]; then
  info "执行本地安全预览；不会访问外部服务"
  set +e
  "$PROJECT_ROOT/.venv/bin/opinion-monitor" \
    --env-file "$ENV_FILE" \
    "${PIPELINE_ARGS[@]}" \
    > "$E2E_ROOT/pipeline-preview.json"
  PREVIEW_RC=$?
  set -e

  "$PROJECT_ROOT/.venv/bin/python" - "$E2E_ROOT/pipeline-preview.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(json.dumps({
    "run_id": payload["run_id"],
    "executed": payload["executed"],
    "status": payload["status"],
    "stages": [
        {"stage": stage["stage"], "status": stage["status"]}
        for stage in payload["stages"]
    ],
}, ensure_ascii=False, indent=2))
PY

  if [[ "$PREVIEW_RC" -ne 0 ]]; then
    die "安全预览失败，退出码：$PREVIEW_RC"
  fi
  info "安全预览完成：$E2E_ROOT"
  exit 0
fi

info "执行真实端到端流水线；如弹出小红书登录二维码，请扫码"
set +e
"$PROJECT_ROOT/.venv/bin/opinion-monitor" \
  --env-file "$ENV_FILE" \
  "${PIPELINE_ARGS[@]}" \
  --execute \
  > "$E2E_ROOT/pipeline-result.json"
PIPELINE_RC=$?
set -e

if [[ ! -s "$E2E_ROOT/pipeline-result.json" ]]; then
  cat "$E2E_ROOT/pipeline-result.json" 2>/dev/null || true
  die "端到端流水线没有生成结果 JSON"
fi

"$PROJECT_ROOT/.venv/bin/python" - "$E2E_ROOT/pipeline-result.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(json.dumps({
    "run_id": payload["run_id"],
    "executed": payload["executed"],
    "status": payload["status"],
    "stages": [
        {
            "stage": stage["stage"],
            "status": stage["status"],
            "error": stage["error"],
            "details": stage["details"],
        }
        for stage in payload["stages"]
    ],
    "storage_stats": payload["storage_stats"],
}, ensure_ascii=False, indent=2))
PY

llm_missing() {
  "$PROJECT_ROOT/.venv/bin/python" - "$DATABASE" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    row = connection.execute(
        """
        SELECT COUNT(*)
        FROM clean_items c
        LEFT JOIN llm_analysis_results r
          ON r.clean_item_id = c.id
        WHERE r.clean_item_id IS NULL
        """
    ).fetchone()
    print(row[0])
PY
}

info "检查并补跑未完成的 LLM 分析"
for attempt in $(seq 1 "$LLM_RETRIES"); do
  MISSING="$(llm_missing)"
  if [[ "$MISSING" -eq 0 ]]; then
    info "LLM 分析已全部完成"
    break
  fi

  info "发现 $MISSING 条待分析条目；第 $attempt 次补跑前等待 $RETRY_DELAY 秒"
  sleep "$RETRY_DELAY"
  set +e
  "$PROJECT_ROOT/.venv/bin/opinion-monitor" \
    --config "$CONFIG" \
    --env-file "$ENV_FILE" \
    run-llm-analysis \
    --all \
    --execute \
    > "$E2E_ROOT/llm-retry-$attempt.json"
  LLM_RC=$?
  set -e

  if [[ "$LLM_RC" -ne 0 ]]; then
    info "LLM 补跑返回非零退出码：$LLM_RC；将继续检查剩余缺口"
  fi
done

info "补跑综合评分"
set +e
"$PROJECT_ROOT/.venv/bin/opinion-monitor" \
  --config "$CONFIG" \
  run-risk-assessment \
  --all \
  > "$E2E_ROOT/risk-retry.json"
RISK_RC=$?
set -e

info "补推尚未成功的钉钉事件"
for attempt in $(seq 1 "$LLM_RETRIES"); do
  set +e
  "$PROJECT_ROOT/.venv/bin/opinion-monitor" \
    --config "$CONFIG" \
    --env-file "$ENV_FILE" \
    send-dingtalk-output \
    --all \
    --include-queued \
    --execute \
    > "$E2E_ROOT/dingtalk-retry-$attempt.json"
  OUTPUT_RC=$?
  set -e

  if [[ "$OUTPUT_RC" -eq 0 ]]; then
    break
  fi
  info "钉钉补推返回非零退出码：$OUTPUT_RC；等待后重试"
  sleep "$RETRY_DELAY"
done

info "执行最终数据库与投递验收"
set +e
SKIP_ACCOUNT="$SKIP_ACCOUNT" "$PROJECT_ROOT/.venv/bin/python" - "$DATABASE" <<'PY'
import json
import sqlite3
import sys

skip_account = os_environ_skip_account = __import__("os").environ["SKIP_ACCOUNT"] == "1"

with sqlite3.connect(sys.argv[1]) as connection:
    connection.row_factory = sqlite3.Row
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_key_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in [
            "raw_items",
            "clean_items",
            "comment_records",
            "llm_analysis_results",
            "risk_assessments",
            "structured_output_events",
            "dingtalk_deliveries",
            "dingtalk_delivery_attempts",
        ]
    }
    missing_analysis = connection.execute(
        """
        SELECT COUNT(*)
        FROM clean_items c
        LEFT JOIN llm_analysis_results r
          ON r.clean_item_id = c.id
        WHERE r.clean_item_id IS NULL
        """
    ).fetchone()[0]
    missing_scoring = connection.execute(
        """
        SELECT COUNT(*)
        FROM clean_items c
        LEFT JOIN risk_assessments r
          ON r.clean_item_id = c.id
        WHERE r.clean_item_id IS NULL
        """
    ).fetchone()[0]
    dingtalk_failed = connection.execute(
        "SELECT COUNT(*) FROM dingtalk_deliveries WHERE status != 'succeeded'"
    ).fetchone()[0]
    dingtalk_succeeded = connection.execute(
        "SELECT COUNT(*) FROM dingtalk_deliveries WHERE status = 'succeeded'"
    ).fetchone()[0]
    source_coverage = [
        dict(row)
        for row in connection.execute(
            """
            SELECT source_type, platform, COUNT(*) AS count
            FROM clean_items
            GROUP BY source_type, platform
            ORDER BY source_type, platform
            """
        )
    ]
    events = [
        dict(row)
        for row in connection.execute(
            """
            SELECT
                json_extract(e.event_json, '$.event_id') AS event_id,
                json_extract(e.event_json, '$.title') AS title,
                json_extract(e.event_json, '$.alert_level') AS alert_level,
                json_extract(e.event_json, '$.overall_score') AS overall_score,
                d.status AS delivery_status,
                d.response_status_code AS http_status_code,
                d.error AS delivery_error
            FROM structured_output_events e
            LEFT JOIN dingtalk_deliveries d
              ON d.event_id = json_extract(e.event_json, '$.event_id')
            ORDER BY e.created_at
            """
        )
    ]

required_sources = ["hotsearch", "keyword_search"]
if not skip_account:
    required_sources.append("account")

errors = []
if integrity != "ok":
    errors.append(f"SQLite integrity_check 异常：{integrity}")
if foreign_key_errors:
    errors.append(f"SQLite 外键错误数：{foreign_key_errors}")
if counts["raw_items"] < 1:
    errors.append("raw_items 为空")
if counts["clean_items"] < 1:
    errors.append("clean_items 为空")
if missing_analysis:
    errors.append(f"仍有 {missing_analysis} 条 CleanItem 未完成 LLM 分析")
if missing_scoring:
    errors.append(f"仍有 {missing_scoring} 条 CleanItem 未完成评分")
if counts["llm_analysis_results"] != counts["clean_items"]:
    errors.append("LLM 分析结果数不等于 CleanItem 数")
if counts["risk_assessments"] != counts["clean_items"]:
    errors.append("风险研判数不等于 CleanItem 数")
if counts["structured_output_events"] != counts["clean_items"]:
    errors.append("结构化事件数不等于 CleanItem 数")
if dingtalk_failed:
    errors.append(f"钉钉投递失败数：{dingtalk_failed}")
if dingtalk_succeeded < 1:
    errors.append("没有成功投递的钉钉事件")
if counts["dingtalk_deliveries"] != counts["structured_output_events"]:
    errors.append("钉钉投递记录数不等于结构化事件数")

available_sources = {row["source_type"] for row in source_coverage}
for source_type in required_sources:
    if source_type not in available_sources:
        errors.append(f"来源覆盖缺少：{source_type}")

result = {
    "status": "failed" if errors else "succeeded",
    "errors": errors,
    "integrity_check": integrity,
    "foreign_key_errors": foreign_key_errors,
    "counts": counts,
    "missing_analysis": missing_analysis,
    "missing_scoring": missing_scoring,
    "dingtalk_succeeded": dingtalk_succeeded,
    "dingtalk_failed": dingtalk_failed,
    "source_coverage": source_coverage,
    "events": events,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
if errors:
    raise SystemExit(1)
PY

FINAL_RC=$?
set -e

ln -sfn "$E2E_ROOT" "$PROJECT_ROOT/data/e2e/latest"

printf '\n端到端测试目录：%s\n' "$E2E_ROOT"
printf '流水线结果：%s\n' "$E2E_ROOT/pipeline-result.json"
printf '钉钉事件数：%s\n' "$( 
  "$PROJECT_ROOT/.venv/bin/python" - "$DATABASE" <<'PY'
import sqlite3
import sys
with sqlite3.connect(sys.argv[1]) as connection:
    print(connection.execute("SELECT COUNT(*) FROM dingtalk_deliveries WHERE status='succeeded'").fetchone()[0])
PY
)"

if [[ "$FINAL_RC" -ne 0 ]]; then
  die "端到端最终验收失败"
fi

info "端到端测试完成"
