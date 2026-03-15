import importlib


def test_telegram_ingress_main_module_imports() -> None:
    module = importlib.import_module("app.main")

    assert module.create_app is not None
