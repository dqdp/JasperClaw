import importlib


def test_agent_api_main_module_imports() -> None:
    module = importlib.import_module("app.main")

    assert module.app is not None
