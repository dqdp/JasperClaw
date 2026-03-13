from __future__ import annotations

from dataclasses import dataclass

from app.modules.webhook.parser import TelegramUpdateParser


@dataclass(frozen=True, slots=True)
class CommandRoute:
    mode: str
    text: str


class CommandRouter:
    """Pure command routing for Telegram text commands."""

    def __init__(self, *, parser: TelegramUpdateParser) -> None:
        self._parser = parser

    def route(self, text: str) -> CommandRoute | None:
        command = self._parser.extract_command(text)
        if command == "/help":
            return CommandRoute(
                mode="local_reply",
                text="Available commands: /help, /status, /ask <message>",
            )
        if command == "/status":
            return CommandRoute(
                mode="local_reply",
                text="telegram-ingress ok",
            )
        if command == "/ask":
            prompt_text = self._parser.extract_command_body(text)
            if not prompt_text:
                return CommandRoute(
                    mode="local_reply",
                    text="Usage: /ask <message>",
                )
            return CommandRoute(mode="completion", text=prompt_text)
        return None
