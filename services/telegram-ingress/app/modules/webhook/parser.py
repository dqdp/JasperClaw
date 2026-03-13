from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TelegramUpdate:
    update_id: int
    chat_id: int
    message_id: int
    user_id: int | None
    text: str


class TelegramUpdateParser:
    """Pure Telegram payload normalization and command-policy helper."""

    def __init__(self, *, allowed_commands: tuple[str, ...] = ()) -> None:
        self._allowed_commands = allowed_commands

    def parse_update(self, payload: dict[str, object]) -> TelegramUpdate | None:
        message = self._extract_message(payload)
        if message is None or self._is_bot_message(message):
            return None

        update_id = self._coerce_int(payload.get("update_id"), None)
        chat_id = self._coerce_int(message.get("chat"), 0, key="id")
        message_id = self._coerce_int(message, 0, key="message_id")
        if chat_id <= 0 or message_id <= 0:
            return None

        text = self._extract_text(message)
        if not text:
            return None

        user_id = None
        from_block = message.get("from")
        if isinstance(from_block, dict):
            user_id = self._coerce_int(from_block, None, key="id")
            if isinstance(user_id, int) and user_id <= 0:
                user_id = None

        return TelegramUpdate(
            update_id=0 if update_id is None else update_id,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            text=text,
        )

    def extract_command(self, text: str) -> str | None:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return None

        command_token = stripped.split(maxsplit=1)[0]
        if not command_token or command_token == "/":
            return None

        return command_token.split("@", 1)[0].lower()

    def extract_command_body(self, text: str) -> str:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return stripped
        parts = stripped.split(maxsplit=1)
        if len(parts) < 2:
            return ""
        return parts[1].strip()

    def is_command_allowed(self, text: str) -> bool:
        if not self._allowed_commands:
            return True

        command = self.extract_command(text)
        if command is None:
            return True

        return command in self._allowed_commands

    def payload_context(self, payload: dict[str, object]) -> dict[str, object]:
        update_id = self._coerce_int(payload.get("update_id"), None)
        message = self._extract_message(payload)
        chat_id = None
        message_id = None
        conversation_id = None
        if message is not None:
            chat_id = self._coerce_int(message.get("chat"), None, key="id")
            message_id = self._coerce_int(message, None, key="message_id")
            if isinstance(chat_id, int) and chat_id > 0:
                conversation_id = f"telegram:{chat_id}"
        return {
            "update_id": update_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "conversation_id": conversation_id,
        }

    def _extract_message(self, payload: dict[str, object]) -> dict[str, object] | None:
        message = payload.get("message")
        if isinstance(message, dict):
            return message
        edited_message = payload.get("edited_message")
        if isinstance(edited_message, dict):
            return edited_message
        return None

    def _is_bot_message(self, message: dict[str, object]) -> bool:
        sender = message.get("from")
        if not isinstance(sender, dict):
            return False
        return sender.get("is_bot") is True

    def _extract_text(self, message: dict[str, object]) -> str:
        text = message.get("text")
        if isinstance(text, str):
            return text.strip()
        caption = message.get("caption")
        if isinstance(caption, str):
            return caption.strip()
        return ""

    def _coerce_int(
        self, source: object, default: int | None, key: str | None = None
    ) -> int | None:
        value = source
        if isinstance(key, str) and isinstance(source, dict):
            value = source.get(key)
        elif key is not None:
            raise ValueError("key is only valid with dict source")

        if not isinstance(value, int) or isinstance(value, bool):
            return default
        return value
