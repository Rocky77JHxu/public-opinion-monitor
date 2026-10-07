"""YAML 配置加载、环境变量展开与安全输出工具。"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from opinion_monitor.config.schema import RootConfig

_ENV_PATTERN = re.compile(r"\$\{(?P<name>[A-Z_][A-Z0-9_]*)(?::-(?P<default>[^}]*))?\}")
_ENV_KEY_SUFFIX = "_env"
_ENV_KEY_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:api_key|token|secret|password|credential|dsn|webhook_url)",
    re.IGNORECASE,
)
_REDACTED = "***已遮蔽***"


class ConfigError(ValueError):
    """配置读取、解析或校验失败。"""


class MissingEnvironmentVariableError(ConfigError):
    """必需环境变量缺失。"""

    def __init__(self, names: list[str]) -> None:
        self.names = sorted(names)
        super().__init__(f"缺失环境变量：{', '.join(self.names)}")


class _UniqueKeyLoader(yaml.SafeLoader):
    """拒绝重复 YAML 键的 SafeLoader。"""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            msg = "YAML 映射键必须可哈希"
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                msg,
                key_node.start_mark,
            ) from exc
        if duplicate:
            msg = f"YAML 映射键重复：{key!r}"
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                msg,
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def read_yaml_config(path: str | Path) -> dict[str, Any]:
    """读取 YAML，并要求根节点为唯一键映射。"""

    config_path = Path(path)
    try:
        document = yaml.load(
            config_path.read_text(encoding="utf-8"),
            # noqa 会被 Ruff 识别在 Loader 参数上；该 Loader 继承 SafeLoader。
            Loader=_UniqueKeyLoader,  # noqa: S506
        )
    except (OSError, yaml.YAMLError) as exc:
        msg = f"无法读取或解析配置文件 {config_path}：{exc}"
        raise ConfigError(msg) from exc
    if not isinstance(document, dict):
        msg = f"配置文件根节点必须是映射，当前类型为 {type(document).__name__}"
        raise ConfigError(msg)
    return document


def expand_env_references(
    value: Any,
    env: Mapping[str, str] | None = None,
) -> Any:
    """递归展开字符串中的 ``${VAR}`` 与 ``${VAR:-default}``。"""

    environment = os.environ if env is None else env

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        if name in environment:
            return environment[name]
        default = match.group("default")
        if default is not None:
            return default
        raise MissingEnvironmentVariableError([name])

    if isinstance(value, str):
        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [expand_env_references(item, environment) for item in value]
    if isinstance(value, dict):
        return {
            expand_env_references(key, environment): expand_env_references(item, environment)
            for key, item in value.items()
        }
    return value


def collect_env_references(value: Any) -> list[str]:
    """收集 ``*_env`` 字段引用的环境变量名。"""

    references: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.endswith(_ENV_KEY_SUFFIX):
                if not isinstance(item, str) or not _ENV_KEY_NAME.fullmatch(item):
                    msg = f"字段 {key} 必须是合法环境变量名，当前为 {item!r}"
                    raise ConfigError(msg)
                references.append(item)
            references.extend(collect_env_references(item))
    elif isinstance(value, list):
        for item in value:
            references.extend(collect_env_references(item))
    return sorted(set(references))


def find_missing_environment_variables(
    value: Any,
    env: Mapping[str, str] | None = None,
) -> list[str]:
    """返回 ``*_env`` 引用但当前环境中不存在的变量。"""

    environment = os.environ if env is None else env
    return [name for name in collect_env_references(value) if name not in environment]


def load_config(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    strict_env: bool = False,
) -> RootConfig:
    """读取 YAML、展开环境变量并执行 Schema 校验。"""

    config_path = Path(path)
    document = read_yaml_config(config_path)
    environment = os.environ if env is None else env

    try:
        expanded = expand_env_references(document, environment)
    except MissingEnvironmentVariableError as exc:
        msg = f"配置文件 {config_path} 中的环境变量引用未满足：{exc}"
        raise ConfigError(msg) from exc

    if strict_env:
        missing = find_missing_environment_variables(expanded, environment)
        if missing:
            raise MissingEnvironmentVariableError(missing)

    try:
        return RootConfig.model_validate(expanded)
    except ValidationError as exc:
        msg = f"配置校验失败：{config_path}\n{exc}"
        raise ConfigError(msg) from exc


def load_env_file(path: str | Path) -> dict[str, str]:
    """解析简单 ``KEY=VALUE`` 环境变量文件。

    支持注释、``export`` 前缀和 POSIX 引号。本函数不会把值写回进程环境。
    """

    env_path = Path(path)
    values: dict[str, str] = {}
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        msg = f"无法读取环境变量文件 {env_path}：{exc}"
        raise ConfigError(msg) from exc

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            msg = f"环境变量文件 {env_path} 第 {line_number} 行引号格式错误：{exc}"
            raise ConfigError(msg) from exc
        if len(tokens) != 1 or "=" not in tokens[0]:
            msg = f"环境变量文件 {env_path} 第 {line_number} 行必须是 KEY=VALUE"
            raise ConfigError(msg)
        key, value = tokens[0].split("=", 1)
        if not _ENV_KEY_NAME.fullmatch(key):
            msg = f"环境变量文件 {env_path} 第 {line_number} 行变量名不合法：{key!r}"
            raise ConfigError(msg)
        values[key] = value
    return values


def build_environment(
    env_file: str | Path | None = None,
    *,
    base_environment: Mapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    """构建 CLI 使用环境；进程内已有变量优先于 env 文件。"""

    environment: dict[str, str] = dict(base_environment or os.environ)
    if env_file is not None:
        for key, value in load_env_file(env_file).items():
            environment.setdefault(key, value)
    return environment


def redact_sensitive_values(value: Any) -> Any:
    """递归遮蔽可能包含秘密或可识别凭据的配置值。"""

    if isinstance(value, dict):
        return {
            key: _REDACTED
            if (
                isinstance(key, str)
                and _SENSITIVE_KEY_PATTERN.search(key)
                and not key.endswith(_ENV_KEY_SUFFIX)
            )
            else redact_sensitive_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_values(item) for item in value]
    return value
