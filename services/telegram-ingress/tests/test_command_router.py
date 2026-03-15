from app.modules.webhook.commands import CommandRoute, CommandRouter
from app.modules.webhook.parser import TelegramUpdateParser


def test_command_router_handles_local_commands() -> None:
    router = CommandRouter(parser=TelegramUpdateParser())

    assert router.route("/help") == CommandRoute(
        mode="discovery_help",
        text="Available commands: /help, /status, /ask <message>, /aliases",
    )
    assert router.route("/status@MyBot") == CommandRoute(
        mode="discovery_status",
        text="Status is temporarily unavailable right now.",
    )
    assert router.route("/aliases") == CommandRoute(
        mode="discovery_aliases",
        text="Aliases are temporarily unavailable right now.",
    )


def test_command_router_handles_ask_command() -> None:
    router = CommandRouter(parser=TelegramUpdateParser())

    assert router.route("/ask   tell me more") == CommandRoute(
        mode="completion",
        text="tell me more",
    )
    assert router.route("/ask") == CommandRoute(
        mode="local_reply",
        text="Usage: /ask <message>",
    )


def test_command_router_returns_none_for_unknown_commands() -> None:
    router = CommandRouter(parser=TelegramUpdateParser())

    assert router.route("/unknown") is None
    assert router.route("plain text") is None
