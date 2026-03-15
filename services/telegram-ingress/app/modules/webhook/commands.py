from __future__ import annotations

from dataclasses import dataclass

from app.modules.webhook.parser import TelegramUpdateParser


@dataclass(frozen=True, slots=True)
class CommandRoute:
    mode: str
    text: str
    alias: str | None = None


class CommandRouter:
    """Pure command routing for Telegram text commands."""

    def __init__(self, *, parser: TelegramUpdateParser) -> None:
        self._parser = parser

    def route(self, text: str) -> CommandRoute | None:
        command = self._parser.extract_command(text)
        if command == "/help":
            return CommandRoute(
                mode="discovery_help",
                text=(
                    "Available commands: /help, /status, /ask <message>, /aliases, "
                    "/send <alias> <message>"
                ),
            )
        if command == "/status":
            return CommandRoute(
                mode="discovery_status",
                text="Status is temporarily unavailable right now.",
            )
        if command == "/aliases":
            return CommandRoute(
                mode="discovery_aliases",
                text="Aliases are temporarily unavailable right now.",
            )
        if command == "/ask":
            prompt_text = self._parser.extract_command_body(text)
            if not prompt_text:
                return CommandRoute(
                    mode="local_reply",
                    text="Usage: /ask <message>",
                )
            return CommandRoute(mode="completion", text=prompt_text)
        if command == "/send":
            body_text = self._parser.extract_command_body(text)
            if not body_text:
                return CommandRoute(
                    mode="local_reply",
                    text="Usage: /send <alias> <message>",
                )
            alias, separator, message_text = body_text.partition(" ")
            if not separator or not message_text.strip():
                return CommandRoute(
                    mode="local_reply",
                    text="Usage: /send <alias> <message>",
                )
            return CommandRoute(
                mode="send_alias",
                text=message_text.strip(),
                alias=alias.strip().casefold(),
            )
        return None
