"""MediaCrawler 隔离子进程 Runner。"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from opinion_monitor.collectors.mediacrawler.models import (
    MediaCrawlerCommandPlan,
    MediaCrawlerRunResult,
    MediaCrawlerRunStatus,
    MediaCrawlerTask,
)
from opinion_monitor.config.schema import MediaCrawlerConfig

T = TypeVar("T")


CommandExecutor = Callable[
    [MediaCrawlerTask, MediaCrawlerCommandPlan],
    Awaitable[tuple[int | None, MediaCrawlerRunStatus, str | None]],
]


def _now() -> datetime:
    return datetime.now(UTC)


class MediaCrawlerRunner:
    """生成任务命令，并只在显式授权后执行子进程。

    默认 `allow_execution=false`，因此 Runner 只返回 skipped，不访问第三方目录、
    不创建浏览器进程、不发起平台请求。这是合规审查前的安全默认值。
    """

    def __init__(
        self,
        config: MediaCrawlerConfig,
        *,
        command_executor: CommandExecutor | None = None,
    ) -> None:
        self._config = config
        self._command_executor = command_executor or self._execute_subprocess

    def build_plan(self, task: MediaCrawlerTask) -> MediaCrawlerCommandPlan:
        wrapper = Path(__file__).with_name("upstream_entry.py")
        argv = [
            self._config.command_name,
            "run",
            "python",
            str(wrapper),
            "--platform",
            task.platform.value,
            "--lt",
            self._config.login_type,
            "--type",
            task.crawl_type,
            "--start",
            "1",
            "--get_comment",
            str(self._config.enable_get_comments).lower(),
            "--get_sub_comment",
            str(self._config.enable_sub_comments).lower(),
            "--get_media",
            "false",
            "--headless",
            str(self._config.headless).lower(),
            "--save_data_option",
            self._config.save_option,
            "--save_data_path",
            str(Path(task.workspace_dir).resolve()),
            "--max_comments_count_singlenotes",
            str(task.max_comments),
            "--crawler_max_notes_count",
            str(task.max_items),
            "--max_concurrency_num",
            str(self._config.max_concurrency),
        ]
        if task.crawl_type == "search":
            argv.extend(("--keywords", task.target))
        elif task.crawl_type == "creator":
            argv.extend(("--creator_id", task.target))
        elif task.crawl_type == "detail":
            argv.extend(("--specified_id", task.target))
        return MediaCrawlerCommandPlan(
            task_id=task.task_id,
            cwd=self._config.root,
            argv=argv,
            input_file=task.input_file,
            output_file=task.output_file,
            stdout_file=(Path(task.workspace_dir) / "stdout.log").as_posix(),
            stderr_file=(Path(task.workspace_dir) / "stderr.log").as_posix(),
            timeout_seconds=task.timeout_seconds,
        )

    async def _execute_subprocess(
        self,
        task: MediaCrawlerTask,
        plan: MediaCrawlerCommandPlan,
    ) -> tuple[int | None, MediaCrawlerRunStatus, str | None]:
        root = Path(plan.cwd)
        entrypoint = root / self._config.entrypoint
        if not root.is_dir() or not entrypoint.is_file():  # noqa: ASYNC240
            return None, MediaCrawlerRunStatus.FAILED, f"MediaCrawler 入口不存在：{entrypoint}"

        git_process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(root),
            "rev-parse",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await git_process.communicate()
        current_ref = stdout.decode("utf-8", errors="replace").strip().lower()
        if git_process.returncode != 0:
            reason = stderr.decode("utf-8", errors="replace").strip()
            return None, MediaCrawlerRunStatus.FAILED, f"无法读取 MediaCrawler 版本：{reason}"
        if current_ref != self._config.pinned_ref.lower():
            return (
                None,
                MediaCrawlerRunStatus.FAILED,
                f"MediaCrawler 版本不匹配："
                f"expected={self._config.pinned_ref}, actual={current_ref}",
            )

        workspace = Path(task.workspace_dir)
        workspace.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        (workspace / "task.json").write_text(task.model_dump_json(), encoding="utf-8")

        with (
            Path(plan.stdout_file).open("w", encoding="utf-8") as stdout_file,  # noqa: ASYNC230
            Path(plan.stderr_file).open("w", encoding="utf-8") as stderr_file,  # noqa: ASYNC230
        ):
            environment = os.environ.copy()
            environment.update(
                {
                    "OPINION_MONITOR_ENABLE_CDP_MODE": str(self._config.enable_cdp_mode).lower(),
                    "OPINION_MONITOR_CDP_CONNECT_EXISTING": str(
                        self._config.enable_cdp_connect_existing
                    ).lower(),
                    "OPINION_MONITOR_CDP_DEBUG_PORT": str(self._config.cdp_debug_port),
                    "OPINION_MONITOR_CDP_HEADLESS": str(self._config.headless).lower(),
                    "OPINION_MONITOR_SAVE_LOGIN_STATE": str(self._config.save_login_state).lower(),
                    "OPINION_MONITOR_CRAWLER_MAX_SLEEP_SEC": str(self._config.max_sleep_seconds),
                }
            )
            process = await asyncio.create_subprocess_exec(
                *plan.argv,
                cwd=plan.cwd,
                env=environment,
                stdout=stdout_file,
                stderr=stderr_file,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=plan.timeout_seconds)
            except TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=10)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                return (
                    process.returncode,
                    MediaCrawlerRunStatus.TIMED_OUT,
                    f"任务超过 {plan.timeout_seconds} 秒",
                )

        if process.returncode == 0:
            return process.returncode, MediaCrawlerRunStatus.SUCCEEDED, None
        return (
            process.returncode,
            MediaCrawlerRunStatus.FAILED,
            f"MediaCrawler 退出码：{process.returncode}",
        )

    async def run(
        self,
        task: MediaCrawlerTask,
        *,
        execute: bool | None = None,
    ) -> MediaCrawlerRunResult:
        started_at = _now()
        plan = self.build_plan(task)
        should_execute = self._config.allow_execution if execute is None else execute

        if not should_execute:
            return MediaCrawlerRunResult(
                task_id=task.task_id,
                status=MediaCrawlerRunStatus.SKIPPED,
                started_at=started_at,
                completed_at=_now(),
                error="allow_execution=false；任务仅生成计划，未执行采集",
            )

        return_code: int | None
        status: MediaCrawlerRunStatus
        error: str | None
        if not self._config.pinned_ref:
            return_code = None
            status = MediaCrawlerRunStatus.FAILED
            error = "缺少 pinned_ref，拒绝执行 MediaCrawler"
        else:
            return_code, status, error = await self._command_executor(task, plan)
        return MediaCrawlerRunResult(
            task_id=task.task_id,
            status=status,
            started_at=started_at,
            completed_at=_now(),
            return_code=return_code,
            error=error,
        )
