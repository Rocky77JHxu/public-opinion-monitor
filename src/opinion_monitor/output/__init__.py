"""钉钉自动化产出层。"""

from opinion_monitor.output.dingtalk import (
    DingTalkOutputError,
    DingTalkOutputService,
    DingTalkWebhookClient,
)

__all__ = [
    "DingTalkOutputError",
    "DingTalkOutputService",
    "DingTalkWebhookClient",
]
