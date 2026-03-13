from app.modules.webhook.parser import TelegramUpdate, TelegramUpdateParser


def test_parse_update_extracts_text_message_fields() -> None:
    parser = TelegramUpdateParser()

    result = parser.parse_update(
        {
            "update_id": 15,
            "message": {
                "message_id": 9,
                "chat": {"id": 42},
                "from": {"id": 77, "is_bot": False},
                "text": "  hello  ",
            },
        }
    )

    assert result == TelegramUpdate(
        update_id=15,
        chat_id=42,
        message_id=9,
        user_id=77,
        text="hello",
    )


def test_parse_update_accepts_edited_message_caption() -> None:
    parser = TelegramUpdateParser()

    result = parser.parse_update(
        {
            "update_id": 16,
            "edited_message": {
                "message_id": 11,
                "chat": {"id": 99},
                "caption": "  caption text ",
            },
        }
    )

    assert result == TelegramUpdate(
        update_id=16,
        chat_id=99,
        message_id=11,
        user_id=None,
        text="caption text",
    )


def test_parse_update_ignores_bot_and_invalid_ids() -> None:
    parser = TelegramUpdateParser()

    assert (
        parser.parse_update(
            {
                "message": {
                    "message_id": 3,
                    "chat": {"id": 4},
                    "from": {"id": 88, "is_bot": True},
                    "text": "hi",
                }
            }
        )
        is None
    )
    assert (
        parser.parse_update(
            {
                "message": {
                    "message_id": 0,
                    "chat": {"id": 4},
                    "text": "hi",
                }
            }
        )
        is None
    )


def test_payload_context_includes_conversation_id_for_valid_chat() -> None:
    parser = TelegramUpdateParser()

    assert parser.payload_context(
        {
            "update_id": 10,
            "message": {
                "message_id": 7,
                "chat": {"id": 123},
            },
        }
    ) == {
        "update_id": 10,
        "chat_id": 123,
        "message_id": 7,
        "conversation_id": "telegram:123",
    }


def test_command_normalization_and_allowlist() -> None:
    parser = TelegramUpdateParser(allowed_commands=("/help", "/ask"))

    assert parser.extract_command(" /Ask@MyBot   hello ") == "/ask"
    assert parser.extract_command_body(" /Ask@MyBot   hello ") == "hello"
    assert parser.is_command_allowed("/help") is True
    assert parser.is_command_allowed("/status") is False
    assert parser.is_command_allowed("plain text") is True
