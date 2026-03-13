"""Webhook facade and related slice entrypoints."""
from .commands import CommandRoute, CommandRouter
from .facade import WebhookFacade
from .parser import TelegramUpdate, TelegramUpdateParser
from .reply_pipeline import ReplyPipeline
from .result import WebhookResult

__all__ = [
    "CommandRoute",
    "CommandRouter",
    "ReplyPipeline",
    "TelegramUpdate",
    "TelegramUpdateParser",
    "WebhookFacade",
    "WebhookResult",
]
