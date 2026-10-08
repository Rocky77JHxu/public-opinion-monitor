from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from opinion_monitor.config import (
    ConfigError,
    MissingEnvironmentVariableError,
    collect_env_references,
    expand_env_references,
    find_missing_environment_variables,
    load_config,
    load_env_file,
    redact_sensitive_values,
)

CONFIG_PATH = Path("config/config.example.yaml")


def test_example_config_passes_schema_validation() -> None:
    config = load_config(CONFIG_PATH, env={})

    assert config.app.name == "opinion-monitor"
    assert config.app.timezone == "Asia/Shanghai"
    assert abs(sum(config.scoring.weights.model_dump().values()) - 1.0) < 1e-9


def test_collects_explicit_environment_references() -> None:
    document = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    assert collect_env_references(document) == [
        "DINGTALK_AUTOMATION_WEBHOOK_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "POSTGRES_DSN",
    ]


def test_finds_missing_explicit_environment_references() -> None:
    document = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    assert find_missing_environment_variables(document, env={}) == collect_env_references(document)
    assert find_missing_environment_variables(document, env={"POSTGRES_DSN": "example"}) == [
        "DINGTALK_AUTOMATION_WEBHOOK_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
    ]


def test_expands_nested_environment_references_with_default() -> None:
    value = {
        "url": "${TEST_URL}/api",
        "name": "${MISSING_NAME:-默认名称}",
        "items": ["${TEST_TOKEN}", "plain"],
    }
    env = {"TEST_URL": "https://example.test", "TEST_TOKEN": "secret-token"}

    result = expand_env_references(value, env)

    assert result == {
        "url": "https://example.test/api",
        "name": "默认名称",
        "items": ["secret-token", "plain"],
    }


def test_missing_placeholder_raises_clear_error() -> None:
    with pytest.raises(MissingEnvironmentVariableError) as exc_info:
        expand_env_references({"value": "${REQUIRED_VALUE}"}, env={})

    assert exc_info.value.names == ["REQUIRED_VALUE"]


def test_strict_env_reports_all_required_variables(tmp_path: Path) -> None:
    with pytest.raises(MissingEnvironmentVariableError) as exc_info:
        load_config(CONFIG_PATH, env={}, strict_env=True)

    assert exc_info.value.names == [
        "DINGTALK_AUTOMATION_WEBHOOK_URL",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "POSTGRES_DSN",
    ]


def test_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.yaml"
    path.write_text("app:\n  name: a\n  name: b\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="映射键重复"):
        load_config(path, env={})


def test_load_env_file_does_not_mutate_process(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text(
        "# 注释\nTEST_ONE=value-one\nexport TEST_TWO='value two'\n",
        encoding="utf-8",
    )

    assert load_env_file(path) == {
        "TEST_ONE": "value-one",
        "TEST_TWO": "value two",
    }


def test_redacts_sensitive_keys_recursively() -> None:
    value = {
        "api_key": "secret",
        "nested": {"webhook_url": "https://example.test/hook", "name": "公开值"},
        "items": [{"password": "secret"}],
    }

    assert redact_sensitive_values(value) == {
        "api_key": "***已遮蔽***",
        "nested": {"webhook_url": "***已遮蔽***", "name": "公开值"},
        "items": [{"password": "***已遮蔽***"}],
    }


def test_mediacrawler_execution_requires_pinned_commit(tmp_path: Path) -> None:
    document = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    document["mediacrawler"]["allow_execution"] = True
    document["mediacrawler"]["pinned_ref"] = ""
    path = tmp_path / "unsafe.yaml"
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ConfigError, match="pinned_ref"):
        load_config(path, env={})

    document["mediacrawler"]["pinned_ref"] = "not-a-commit"
    path.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match="40 位小写"):
        load_config(path, env={})
