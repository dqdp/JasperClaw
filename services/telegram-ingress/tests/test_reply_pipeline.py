import pytest

from app.clients.agent_api import AgentApiError, AgentApiClient
from app.clients.telegram import TelegramClient, TelegramSendError
from app.modules.webhook.parser import TelegramUpdate
from app.modules.webhook.reply_pipeline import ReplyPipeline
from app.modules.webhook.result import WebhookResult


class _FakeAgentApiClient(AgentApiClient):
    def __init__(self, *, response_text: str = "reply", fail: bool = False) -> None:
        self.calls: list[dict[str, str]] = []
        self.response_text = response_text
        self.fail = fail

    async def complete(
        self,
        *,
        model: str,
        text: str,
        conversation_id: str,
        request_id: str,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "text": text,
                "conversation_id": conversation_id,
                "request_id": request_id,
            }
        )
        if self.fail:
            raise AgentApiError("agent unavailable")
        return self.response_text


class _FakeTelegramClient(TelegramClient):
    def __init__(self, *, fail: bool = False) -> None:
        self.sent_messages: list[tuple[int, str]] = []
        self.fail = fail

    async def send_message(self, *, chat_id: int, text: str) -> None:
        if self.fail:
            raise TelegramSendError("telegram unavailable")
        self.sent_messages.append((chat_id, text))


class _RetryableError(RuntimeError):
    pass


@pytest.fixture
def update() -> TelegramUpdate:
    return TelegramUpdate(
        update_id=10,
        chat_id=42,
        message_id=9,
        user_id=7,
        text="hello",
    )


def _pipeline(
    *,
    agent_client: _FakeAgentApiClient | None = None,
    telegram_client: _FakeTelegramClient | None = None,
    released: list[TelegramUpdate] | None = None,
    max_reply_chars: int = 20,
) -> ReplyPipeline:
    released = released if released is not None else []

    async def _release_retry_state(update: TelegramUpdate) -> None:
        released.append(update)

    return ReplyPipeline(
        agent_client=agent_client or _FakeAgentApiClient(),
        telegram_client=telegram_client or _FakeTelegramClient(),
        agent_model="assistant-fast",
        max_reply_chars=max_reply_chars,
        release_retry_state=_release_retry_state,
        retryable_error_factory=_RetryableError,
    )


@pytest.mark.anyio
async def test_reply_pipeline_sends_local_reply(update: TelegramUpdate) -> None:
    telegram_client = _FakeTelegramClient()
    pipeline = _pipeline(telegram_client=telegram_client)

    result = await pipeline.send_local_reply(
        update=update,
        conversation_id="telegram:42",
        text="local",
    )

    assert result == WebhookResult.ok(
        status="processed",
        update_id=10,
        chat_id=42,
        message_id=9,
        conversation_id="telegram:42",
    )
    assert telegram_client.sent_messages == [(42, "local")]


@pytest.mark.anyio
async def test_reply_pipeline_completes_and_truncates_reply(
    update: TelegramUpdate,
) -> None:
    agent_client = _FakeAgentApiClient(response_text="abcdefghijklmnopqrstuvwxyz")
    telegram_client = _FakeTelegramClient()
    pipeline = _pipeline(
        agent_client=agent_client,
        telegram_client=telegram_client,
        max_reply_chars=5,
    )

    result = await pipeline.complete_and_send(
        update=update,
        conversation_id="telegram:42",
        prompt_text="prompt",
        request_id="req_123",
    )

    assert result.status == "processed"
    assert agent_client.calls == [
        {
            "model": "assistant-fast",
            "text": "prompt",
            "conversation_id": "telegram:42",
            "request_id": "req_123",
        }
    ]
    assert telegram_client.sent_messages == [(42, "abcde")]


@pytest.mark.anyio
async def test_reply_pipeline_releases_retry_state_on_local_send_failure(
    update: TelegramUpdate,
) -> None:
    released: list[TelegramUpdate] = []
    pipeline = _pipeline(
        telegram_client=_FakeTelegramClient(fail=True),
        released=released,
    )

    with pytest.raises(_RetryableError):
        await pipeline.send_local_reply(
            update=update,
            conversation_id="telegram:42",
            text="local",
        )

    assert released == [update]


@pytest.mark.anyio
async def test_reply_pipeline_releases_retry_state_on_completion_failure(
    update: TelegramUpdate,
) -> None:
    released: list[TelegramUpdate] = []
    pipeline = _pipeline(
        agent_client=_FakeAgentApiClient(fail=True),
        released=released,
    )

    with pytest.raises(_RetryableError):
        await pipeline.complete_and_send(
            update=update,
            conversation_id="telegram:42",
            prompt_text="prompt",
            request_id="req_123",
        )

    assert released == [update]
